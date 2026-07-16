#!/usr/bin/env python3
"""
Fetch congressional data from the Congress.gov API.

Requires a free API key from https://api.congress.gov/sign-up/
Set it as an environment variable named CONGRESS_API_KEY.

Outputs: public/congress_data.json
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://api.congress.gov/v3"
API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()

# Seconds between requests. The API allows 5,000/hour; this keeps us well under.
REQUEST_DELAY = 0.3

# How many sponsored bills to keep per member (keeps the JSON a sane size).
BILLS_PER_MEMBER = 20

OUTPUT_PATH = os.path.join("public", "congress_data.json")


class CongressDataFetcher:
    def __init__(self, api_key: str):
        if not api_key:
            print(
                "ERROR: No API key found.\n"
                "  Get a free key at https://api.congress.gov/sign-up/\n"
                "  Then add it to your repo as a secret named CONGRESS_API_KEY\n"
                "  (Settings > Secrets and variables > Actions > New repository secret).",
                file=sys.stderr,
            )
            sys.exit(1)

        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "congress-tracker/1.0"})

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """GET an endpoint with the API key attached. Returns {} on failure."""
        time.sleep(REQUEST_DELAY)
        params = dict(params or {})
        params["api_key"] = self.api_key
        params.setdefault("format", "json")
        url = f"{API_BASE}{endpoint}"

        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                print("  Rate limited; waiting 60s...")
                time.sleep(60)
                resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            # Don't leak the key into logs.
            print(f"  Request failed for {endpoint}: {e}", file=sys.stderr)
            return {}

    def fetch_members(self) -> List[Dict[str, Any]]:
        """Fetch all current members of Congress (House + Senate)."""
        print("Fetching current members...")
        members = []
        offset = 0
        limit = 250

        while True:
            data = self._request(
                "/member",
                {"currentMember": "true", "limit": limit, "offset": offset},
            )
            batch = data.get("members", [])
            if not batch:
                break

            for m in batch:
                parsed = self._parse_member(m)
                if parsed:
                    members.append(parsed)

            print(f"  {len(members)} members so far...")

            pagination = data.get("pagination", {}) or {}
            total = pagination.get("count")
            if total is None or len(members) >= total or len(batch) < limit:
                break
            offset += limit

        return members

    def _parse_member(self, m: Dict) -> Optional[Dict[str, Any]]:
        """Normalize one member record from the API into our shape."""
        bioguide_id = m.get("bioguideId")
        if not bioguide_id:
            return None

        # The /member list endpoint returns "Last, First" in `name`.
        raw_name = m.get("name") or ""
        if "," in raw_name:
            last, first = [p.strip() for p in raw_name.split(",", 1)]
            display_name = f"{first} {last}"
        else:
            display_name = raw_name

        # `terms` is a dict with an "item" list of served terms.
        terms = ((m.get("terms") or {}).get("item")) or []
        chamber = None
        term_start = None
        term_end = None
        if terms:
            latest = terms[-1]
            chamber = latest.get("chamber")
            term_start = latest.get("startYear")
            term_end = latest.get("endYear")

        return {
            "bioguideId": bioguide_id,
            "name": display_name,
            "party": m.get("partyName") or "Unknown",
            "state": m.get("state"),
            "chamber": chamber,
            "district": m.get("district"),
            "termStart": str(term_start) if term_start else None,
            "termEnd": str(term_end) if term_end else None,
            "termsServed": len(terms) if terms else None,
            "website": m.get("url"),
            "bills": [],
            "source": "Congress.gov API",
            "sourceUrl": f"https://www.congress.gov/member/{bioguide_id}",
        }

    def fetch_sponsored_bills(self, bioguide_id: str) -> List[Dict[str, Any]]:
        """Fetch legislation sponsored by a member."""
        data = self._request(
            f"/member/{bioguide_id}/sponsored-legislation",
            {"limit": BILLS_PER_MEMBER},
        )
        items = data.get("sponsoredLegislation", []) or []

        bills = []
        for b in items:
            number = b.get("number")
            bill_type = (b.get("type") or "").lower()
            congress = b.get("congress")
            if not (number and bill_type and congress):
                continue

            bills.append(
                {
                    "billNumber": f"{(b.get('type') or '').upper()} {number}",
                    "title": b.get("title") or "",
                    "introducedDate": b.get("introducedDate"),
                    "latestAction": ((b.get("latestAction") or {}).get("text")) or "",
                    "role": "sponsor",
                    "source": "Congress.gov API",
                    "sourceUrl": (
                        f"https://www.congress.gov/bill/{congress}th-congress/"
                        f"{bill_type}/{number}"
                    ),
                }
            )
        return bills

    def run(self) -> Dict[str, Any]:
        members = self.fetch_members()
        print(f"Fetched {len(members)} members.\n")

        print("Fetching sponsored bills per member...")
        for i, member in enumerate(members, start=1):
            member["bills"] = self.fetch_sponsored_bills(member["bioguideId"])
            if i % 25 == 0:
                print(f"  {i}/{len(members)} members processed")

        return {
            "lastUpdated": datetime.utcnow().isoformat() + "Z",
            "totalMembers": len(members),
            "members": members,
            "metadata": {
                "dataSource": "Congress.gov API",
                "sourceUrl": "https://api.congress.gov",
            },
        }


def main():
    fetcher = CongressDataFetcher(API_KEY)
    data = fetcher.run()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, indent=2)

    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"\nWrote {OUTPUT_PATH}")
    print(f"  Members: {data['totalMembers']}")
    print(f"  Size: {size_mb:.1f} MB")
    print(f"  Last updated: {data['lastUpdated']}")


if __name__ == "__main__":
    main()
