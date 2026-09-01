#!/usr/bin/env python3
"""
Build public/congress_data.json for the Congressional Tracker.

Two data sources, each used for what it's actually good at:

  1. congress-legislators (github.com/unitedstates/congress-legislators)
     Member roster, party, and full term history with exact start/end dates.
     One HTTP request, no API key, public domain. This is the authoritative
     source for "how many terms" and "when are they up for re-election" --
     the Congress.gov API groups service by Congress, not by term, which is
     why term counts derived from it are wrong for senators.

  2. Congress.gov API (api.congress.gov)
     Sponsored legislation per member. Requires a free API key:
     https://api.congress.gov/sign-up/
     Set it as an env var / repo secret named CONGRESS_API_KEY.

If the API key is missing, the script still produces a complete file with
every member, term, and election date -- just without bills. It does not
hard-fail, because partial data beats no data.
"""

import os
import sys
import json
import time
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional

import requests

from fec_finance import add_finance
from votes import add_votes
from committees import add_committees

# ---------- config ----------

LEGISLATORS_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators/"
    "gh-pages/legislators-current.json"
)

CONGRESS_API_BASE = "https://api.congress.gov/v3"
API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()

# Seconds between Congress.gov requests. The API allows 5,000/hour.
REQUEST_DELAY = 0.3

# Sponsored bills to keep per member. Members like Grassley have sponsored
# thousands over 50 years; we keep the most recent N to hold the JSON to a
# size the browser can parse quickly.
BILLS_PER_MEMBER = 15

OUTPUT_PATH = os.path.join("public", "congress_data.json")

PARTY_FULL = {
    "Democrat": "Democratic",
    "Republican": "Republican",
    "Independent": "Independent",
}

CHAMBER_FULL = {"sen": "Senate", "rep": "House"}

# The roster uses two-letter codes; spell them out so the State filter and
# the search box work the way people expect ("Washington", not "WA").
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    # Non-state delegations, which do have members in Congress.
    "DC": "District of Columbia", "PR": "Puerto Rico", "VI": "Virgin Islands",
    "GU": "Guam", "AS": "American Samoa", "MP": "Northern Mariana Islands",
}


# ---------- member roster ----------


def fetch_legislators() -> List[Dict[str, Any]]:
    """Download the current legislator roster. One request, no key needed."""
    print("Fetching legislator roster...")
    resp = requests.get(LEGISLATORS_URL, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    print(f"  Got {len(data)} current members "
          f"({len(resp.content) / 1048576:.1f} MB)\n")
    return data


def parse_term_dates(term: Dict) -> tuple:
    """Return (start_date, end_date) as date objects, or (None, None)."""
    def parse(s):
        try:
            return date.fromisoformat(s)
        except (TypeError, ValueError):
            return None

    return parse(term.get("start")), parse(term.get("end"))


def build_member(person: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn one congress-legislators record into our row shape."""
    ids = person.get("id") or {}
    bioguide = ids.get("bioguide")
    terms = person.get("terms") or []
    if not bioguide or not terms:
        return None

    name_obj = person.get("name") or {}
    name = name_obj.get("official_full")
    if not name:
        first = name_obj.get("nickname") or name_obj.get("first") or ""
        last = name_obj.get("last") or ""
        name = f"{first} {last}".strip()

    # Terms are already in chronological order in this dataset, but sort
    # defensively -- a bad order would silently corrupt every derived field.
    terms = sorted(terms, key=lambda t: t.get("start") or "")
    current = terms[-1]
    first_term = terms[0]

    start_date, end_date = parse_term_dates(current)
    first_start, _ = parse_term_dates(first_term)

    # A term ends in early January; the election deciding the seat is the
    # November before that. So end year - 1 is the election year.
    next_election = end_date.year - 1 if end_date else None

    chamber_code = current.get("type")
    party = current.get("party") or "Unknown"

    return {
        "bioguideId": bioguide,
        "name": name,
        "party": PARTY_FULL.get(party, party),
        "state": STATE_NAMES.get(current.get("state"), current.get("state")),
        "stateCode": current.get("state"),
        "chamber": CHAMBER_FULL.get(chamber_code, chamber_code),
        "district": current.get("district"),
        "termStart": current.get("start"),
        "termEnd": current.get("end"),
        "termsServed": len(terms),
        "firstYearServed": str(first_start.year) if first_start else None,
        "nextElection": str(next_election) if next_election else None,
        "website": current.get("url"),
        "phone": current.get("phone"),
        "bills": [],
        "billsTotal": None,
        "source": "unitedstates/congress-legislators",
        # The underscore stands in for the name slug; Congress.gov resolves it
        # for any member serving from the 93rd Congress (1973) onward.
        "sourceUrl": f"https://www.congress.gov/member/_/{bioguide}",
    }


# ---------- sponsored bills ----------


class BillFetcher:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.failures = 0
        self.dropped = 0
        self.debugged = False

    def fetch(self, bioguide_id: str) -> List[Dict[str, Any]]:
        time.sleep(REQUEST_DELAY)
        url = f"{CONGRESS_API_BASE}/member/{bioguide_id}/sponsored-legislation"
        params = {
            "api_key": self.api_key,
            "format": "json",
            "limit": BILLS_PER_MEMBER,
        }

        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                print("  Rate limited; waiting 60s...")
                time.sleep(60)
                resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            # Never print the URL -- it carries the API key.
            print(f"  Bill request failed for {bioguide_id}: {e}", file=sys.stderr)
            self.failures += 1
            return [], None

        items = data.get("sponsoredLegislation") or []

        # The real total (members can sponsor hundreds); the API reports it in
        # pagination.count. We show recent BILLS_PER_MEMBER but surface the
        # true total so the UI doesn't imply everyone sponsored exactly 15.
        total_count = None
        pag = data.get("pagination") or {}
        if isinstance(pag, dict):
            total_count = pag.get("count")

        # One-time dump of the raw shape. If bills come back empty or short,
        # this is what tells us why, instead of another round of guessing.
        if not self.debugged and items:
            self.debugged = True
            print("\n  [debug] raw sponsoredLegislation item:")
            print("  " + json.dumps(items[0], indent=2)[:600].replace("\n", "\n  "))
            print(f"  [debug] response keys: {list(data.keys())}")
            print(f"  [debug] pagination: {pag}")
            print(f"  [debug] items returned: {len(items)}\n")

        bills = []
        for b in items:
            if not isinstance(b, dict):
                self.dropped += 1
                continue

            # Bills carry `number`; amendments carry `amendmentNumber` and an
            # amendment type like SAMDT. Accept both instead of dropping.
            number = b.get("number") or b.get("amendmentNumber")
            bill_type = (b.get("type") or "").strip()
            congress = b.get("congress")

            if not number:
                self.dropped += 1
                continue

            label = f"{bill_type.upper()} {number}" if bill_type else f"Measure {number}"

            # Only build a link if we have every piece it needs; a broken
            # link is worse than no link on a transparency tool.
            source_url = None
            if bill_type and congress:
                source_url = (
                    f"https://www.congress.gov/bill/{congress}th-congress/"
                    f"{bill_type.lower()}/{number}"
                )

            bills.append(
                {
                    "billNumber": label,
                    "title": b.get("title") or "",
                    "introducedDate": b.get("introducedDate"),
                    "latestAction": ((b.get("latestAction") or {}).get("text")) or "",
                    "policyArea": ((b.get("policyArea") or {}).get("name")) or "",
                    "role": "sponsor",
                    "source": "Congress.gov API",
                    "sourceUrl": source_url,
                }
            )

        return bills, total_count


# ---------- orchestration ----------


def main():
    roster = fetch_legislators()

    members = []
    fec_id_by_bioguide = {}
    for person in roster:
        row = build_member(person)
        if row:
            members.append(row)
            # Stash each member's FEC candidate IDs for the finance pass.
            fec_ids = (person.get("id") or {}).get("fec") or []
            if isinstance(fec_ids, str):
                fec_ids = [fec_ids]
            fec_id_by_bioguide[row["bioguideId"]] = fec_ids

    print(f"Built {len(members)} member records.\n")

    # ---- committee assignments (congress-legislators, no key) ----
    committees_enabled = add_committees(members)
    print()

    if not members:
        print("ERROR: No members parsed. Aborting.", file=sys.stderr)
        sys.exit(1)

    bills_enabled = bool(API_KEY)
    if not bills_enabled:
        print("WARNING: CONGRESS_API_KEY is not set.")
        print("  Writing member data without sponsored bills.")
        print("  Get a free key at https://api.congress.gov/sign-up/ and add it")
        print("  as a repo secret named CONGRESS_API_KEY to enable bills.\n")
    else:
        print("Fetching sponsored bills from Congress.gov...")
        fetcher = BillFetcher(API_KEY)
        for i, member in enumerate(members, start=1):
            member["bills"], member["billsTotal"] = fetcher.fetch(member["bioguideId"])
            if i % 50 == 0:
                print(f"  {i}/{len(members)} members processed")

    # ---- campaign finance (FEC) ----
    finance_enabled = add_finance(members, fec_id_by_bioguide)

    # ---- federal roll-call votes (GovTrack) ----
    # The 119th Congress convened Jan 2025 and runs through Jan 2027. Derive
    # the current Congress number from the year so this stays correct over time:
    # Congress N covers years [1789 + 2*(N-1), ...]; 119th = 2025-2026.
    current_year = datetime.now(timezone.utc).year
    current_congress = (current_year - 2025) // 2 + 119
    votes_enabled = add_votes(members, current_congress)

    # Sanity checks. A silent parse regression should be loud, not invisible.
    total = len(members)
    have_party = sum(1 for m in members if m["party"] != "Unknown")
    have_terms = sum(1 for m in members if m["termsServed"])
    have_election = sum(1 for m in members if m["nextElection"])
    have_bills = sum(1 for m in members if m["bills"])

    print("\n--- Data quality ---")
    print(f"  Party:         {have_party}/{total}")
    print(f"  Terms served:  {have_terms}/{total}")
    print(f"  Next election: {have_election}/{total}")
    if bills_enabled:
        print(f"  With bills:    {have_bills}/{total}")
        print(f"  Failed bill requests: {fetcher.failures}")
        print(f"  Dropped bill items:   {fetcher.dropped}")
    else:
        print("  With bills:    skipped (no API key)")

    payload = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "totalMembers": total,
        "billsIncluded": bills_enabled,
        "financeIncluded": finance_enabled,
        "votesIncluded": votes_enabled,
        "committeesIncluded": committees_enabled,
        "members": members,
        "metadata": {
            "memberSource": "unitedstates/congress-legislators (public domain)",
            "memberSourceUrl": "https://github.com/unitedstates/congress-legislators",
            "billSource": "Congress.gov API",
            "billSourceUrl": "https://api.congress.gov",
            "financeSource": "OpenFEC API (Federal Election Commission)",
            "financeSourceUrl": "https://api.open.fec.gov",
            "voteSource": "GovTrack / unitedstates congress project (public domain)",
            "voteSourceUrl": "https://www.govtrack.us/congress/votes",
            "termNote": (
                "Terms and dates come from the congress-legislators dataset, "
                "which records one entry per elected term with exact start and "
                "end dates. Next election is the November before the current "
                "term ends."
            ),
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    size_mb = os.path.getsize(OUTPUT_PATH) / 1048576
    print(f"\nWrote {OUTPUT_PATH}")
    print(f"  Members: {total}")
    print(f"  Size: {size_mb:.1f} MB")
    print(f"  Last updated: {payload['lastUpdated']}")


if __name__ == "__main__":
    main()
