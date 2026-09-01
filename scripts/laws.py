#!/usr/bin/env python3
"""
laws.py — enacted laws this Congress, by sponsor party and per member.

Source: Congress.gov API (same CONGRESS_API_KEY).
  List:   /law/{congress}/pub          every bill that became PUBLIC law
  Detail: /bill/{congress}/{type}/{number}   -> sponsors[].bioguideId

We resolve each law's sponsor to a party through OUR roster (Bioguide ID ->
member), so the party comes from the same source as everything else and we
never depend on the API's party string.

Adds:
  payload["lawsByParty"] = {
      "congress": 119, "total": N,
      "Democratic": n, "Republican": n, "Independent": n, "Unknown": n,
      "source": "...", "sourceUrl": "..."
  }
  member["lawsEnacted"] = count of laws this member sponsored that passed

Honesty notes shown in the UI (kept here so they travel with the data):
  - The majority party structurally passes more; this is not a merit score.
  - A share of enacted laws are ceremonial (namings, commemorations).
"""

import os
import sys
import json
import time
from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://api.congress.gov/v3"
API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()
REQUEST_DELAY = 0.3

# Safety cap on detail lookups; a Congress rarely exceeds ~500 public laws.
MAX_LAWS = 800


class LawFetcher:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.failures = 0
        self._dumped_list = False
        self._dumped_item = False

    def _get(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        time.sleep(REQUEST_DELAY)
        p = dict(params or {})
        p["api_key"] = self.api_key
        p["format"] = "json"
        url = f"{API_BASE}{path}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=p, timeout=30)
                if r.status_code == 429:
                    wait = 20 * (attempt + 1)
                    print(f"  [laws] rate limited; waiting {wait}s")
                    time.sleep(wait)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    print(f"  [laws] request failed ({path}): {e}", file=sys.stderr)
                    self.failures += 1
                    return None
                time.sleep(5)
        return None

    def list_public_laws(self, congress: int) -> List[Dict]:
        """All bills that became public law this Congress (paginated)."""
        out: List[Dict] = []
        offset = 0
        while len(out) < MAX_LAWS:
            data = self._get(f"/law/{congress}/pub", {"limit": 250, "offset": offset})
            if not data:
                break
            if not self._dumped_list:
                self._dumped_list = True
                print("\n  [debug] law list response keys:", list(data.keys()))
                for k, v in data.items():
                    if isinstance(v, list) and v:
                        print(f"  [debug] first item in '{k}':",
                              json.dumps(v[0], indent=2)[:500].replace("\n", "\n  "))
                        break
                print()
            batch = None
            for k in ("bills", "laws", "results"):
                if isinstance(data.get(k), list):
                    batch = data[k]
                    break
            if batch is None:
                for v in data.values():
                    if isinstance(v, list):
                        batch = v
                        break
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 250:
                break
            offset += 250
        return out

    def sponsor_bioguide(self, congress: int, bill_type: str, number) -> Optional[str]:
        data = self._get(f"/bill/{congress}/{bill_type.lower()}/{number}")
        if not data:
            return None
        bill = data.get("bill") or data
        if not self._dumped_item:
            self._dumped_item = True
            sp = bill.get("sponsors")
            print("  [debug] bill item keys:", list(bill.keys())[:20])
            print("  [debug] sponsors:", json.dumps(sp)[:300], "\n")
        sponsors = bill.get("sponsors") or []
        if isinstance(sponsors, dict):
            sponsors = sponsors.get("item") or []
        for s in sponsors:
            if isinstance(s, dict) and s.get("bioguideId"):
                return s["bioguideId"]
        return None


def add_laws(members: List[Dict[str, Any]], congress: int) -> Optional[Dict[str, Any]]:
    """Tally enacted public laws by sponsor party. Returns the summary dict."""
    for m in members:
        m["lawsEnacted"] = 0

    if not API_KEY:
        print("WARNING: CONGRESS_API_KEY not set -- skipping enacted laws.")
        return None

    print(f"Fetching enacted public laws (Congress {congress})...")
    f = LawFetcher(API_KEY)
    laws = f.list_public_laws(congress)
    print(f"  {len(laws)} public laws listed.")

    if not laws:
        print(f"  Failed requests: {f.failures}")
        return None

    by_bioguide = {m["bioguideId"]: m for m in members}
    tally = {"Democratic": 0, "Republican": 0, "Independent": 0, "Unknown": 0}

    for i, law in enumerate(laws, start=1):
        bt = law.get("type") or law.get("billType")
        num = law.get("number") or law.get("billNumber")
        if not (bt and num):
            tally["Unknown"] += 1
            continue
        bid = f.sponsor_bioguide(congress, bt, num)
        m = by_bioguide.get(bid) if bid else None
        if m:
            party = m.get("party") or "Unknown"
            tally[party if party in tally else "Unknown"] += 1
            m["lawsEnacted"] += 1
        else:
            # Sponsor not a current member (retired/left office mid-term).
            tally["Unknown"] += 1
        if i % 50 == 0:
            print(f"  {i}/{len(laws)} laws processed")

    summary = {
        "congress": congress,
        "total": len(laws),
        **tally,
        "source": "Congress.gov API — enacted public laws",
        "sourceUrl": f"https://www.congress.gov/public-laws/{congress}th-congress",
    }

    print("\n--- Enacted laws ---")
    for k in ("Democratic", "Republican", "Independent", "Unknown"):
        print(f"  {k:12} {tally[k]}")
    print(f"  Failed requests: {f.failures}")
    return summary
