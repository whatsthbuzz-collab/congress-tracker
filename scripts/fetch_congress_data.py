#!/usr/bin/env python3
"""
Fetch congressional data from the Congress.gov API.

Requires a free API key from https://api.congress.gov/sign-up/
Set it as an environment variable named CONGRESS_API_KEY.

Outputs: public/congress_data.json

Notes on term counting:
  The /member list endpoint groups service by CHAMBER, not by term, so it
  can't be used to count terms. This script calls /member/{bioguideId} for
  each person, which returns one entry per Congress served. Counting those
  entries gives an accurate term count, and the most recent entry gives the
  current term's start/end years.
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

# Seconds between requests. The API allows 5,000/hour.
# This script makes roughly 3 calls per member (~1,600 total), so this
# delay keeps the whole run around 10 minutes and well under the limit.
REQUEST_DELAY = 0.3

# How many sponsored bills to keep per member (keeps the JSON a sane size).
BILLS_PER_MEMBER = 10

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
        self.failures = 0

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
            self.failures += 1
            return {}

    # ---------- members ----------

    def fetch_member_ids(self) -> List[str]:
        """Fetch bioguide IDs for all current members of Congress."""
        print("Fetching current member list...")
        ids = []
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
                bid = m.get("bioguideId")
                if bid:
                    ids.append(bid)

            print(f"  {len(ids)} members so far...")

            if len(batch) < limit:
                break
            offset += limit

        # De-dupe, just in case.
        return list(dict.fromkeys(ids))

    def fetch_member_detail(self, bioguide_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch full detail for one member, including complete term history.

        The detail endpoint returns `terms` as a flat list with one entry per
        Congress served, each with chamber/congress/startYear/endYear.
        """
        data = self._request(f"/member/{bioguide_id}")
        m = data.get("member")
        if not m:
            return None

        # ----- name -----
        display_name = m.get("directOrderName")
        if not display_name:
            first = m.get("firstName") or ""
            last = m.get("lastName") or ""
            display_name = f"{first} {last}".strip()
        if not display_name:
            raw = m.get("invertedOrderName") or m.get("name") or ""
            if "," in raw:
                last, first = [p.strip() for p in raw.split(",", 1)]
                display_name = f"{first} {last}"
            else:
                display_name = raw

        # ----- terms -----
        # On the detail endpoint `terms` is usually a plain list. Older/other
        # shapes wrap it as {"item": [...]}. Handle both.
        raw_terms = m.get("terms")
        if isinstance(raw_terms, dict):
            terms = raw_terms.get("item") or []
        elif isinstance(raw_terms, list):
            terms = raw_terms
        else:
            terms = []

        # Sort chronologically so "latest" is genuinely the current term.
        def term_sort_key(t):
            return (t.get("congress") or 0, t.get("startYear") or 0)

        terms = sorted(
            [t for t in terms if isinstance(t, dict)], key=term_sort_key
        )

        terms_served = len(terms) if terms else None
        current = terms[-1] if terms else {}

        chamber = current.get("chamber")
        term_start = current.get("startYear")
        term_end = current.get("endYear")
        district = current.get("district")
        state = current.get("state") or m.get("state")

        # First year they ever served — useful context, and it's what people
        # usually mean by "how long have they been there".
        first_year = terms[0].get("startYear") if terms else None

        # ----- party -----
        # partyHistory is a list; the last entry is the current affiliation.
        party = None
        party_history = m.get("partyHistory")
        if isinstance(party_history, list) and party_history:
            party = party_history[-1].get("partyName")
        if not party:
            party = m.get("partyName") or current.get("partyName")
        if not party:
            party = "Unknown"

        # ----- next election -----
        # A term ends in early January, and the election that decides the seat
        # is the November before that. So endYear - 1 is the election year.
        next_election = None
        if isinstance(term_end, int):
            next_election = term_end - 1 if term_end > 2000 else None

        return {
            "bioguideId": bioguide_id,
            "name": display_name,
            "party": party,
            "state": state,
            "chamber": chamber,
            "district": district,
            "termStart": str(term_start) if term_start else None,
            "termEnd": str(term_end) if term_end else None,
            "termsServed": terms_served,
            "firstYearServed": str(first_year) if first_year else None,
            "nextElection": str(next_election) if next_election else None,
            "website": m.get("officialWebsiteUrl") or m.get("url"),
            "bills": [],
            "source": "Congress.gov API",
            "sourceUrl": f"https://www.congress.gov/member/{bioguide_id}",
        }

    # ---------- bills ----------

    def fetch_sponsored_bills(self, bioguide_id: str) -> List[Dict[str, Any]]:
        """Fetch legislation sponsored by a member."""
        data = self._request(
            f"/member/{bioguide_id}/sponsored-legislation",
            {"limit": BILLS_PER_MEMBER},
        )
        items = data.get("sponsoredLegislation", []) or []

        bills = []
        for b in items:
            if not isinstance(b, dict):
                continue
            number = b.get("number")
            bill_type = (b.get("type") or "").lower()
            congress = b.get("congress")
            if not (number and bill_type and congress):
                continue

            bills.append(
                {
                    "billNumber": f"{bill_type.upper()} {number}",
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

    # ---------- orchestration ----------

    def run(self) -> Dict[str, Any]:
        ids = self.fetch_member_ids()
        print(f"Found {len(ids)} current members.\n")

        if not ids:
            print("ERROR: No members returned. Check the API key.", file=sys.stderr)
            sys.exit(1)

        print("Fetching detail + bills for each member...")
        members = []
        for i, bid in enumerate(ids, start=1):
            detail = self.fetch_member_detail(bid)
            if not detail:
                print(f"  Skipped {bid} (no detail returned)")
                continue

            detail["bills"] = self.fetch_sponsored_bills(bid)
            members.append(detail)

            if i % 25 == 0:
                print(f"  {i}/{len(ids)} processed")

        # Sanity checks, so a silent parse failure doesn't ship quietly.
        missing_party = sum(1 for m in members if m["party"] == "Unknown")
        missing_terms = sum(1 for m in members if not m["termsServed"])
        with_bills = sum(1 for m in members if m["bills"])

        print("\n--- Data quality ---")
        print(f"  Members with a party:      {len(members) - missing_party}/{len(members)}")
        print(f"  Members with a term count: {len(members) - missing_terms}/{len(members)}")
        print(f"  Members with bills:        {with_bills}/{len(members)}")
        print(f"  Failed requests:           {self.failures}")

        return {
            "lastUpdated": datetime.utcnow().isoformat() + "Z",
            "totalMembers": len(members),
            "members": members,
            "metadata": {
                "dataSource": "Congress.gov API",
                "sourceUrl": "https://api.congress.gov",
                "termNote": (
                    "Terms are counted as one per Congress served, from the "
                    "member's full term history. Next election is derived from "
                    "the current term's end year."
                ),
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
