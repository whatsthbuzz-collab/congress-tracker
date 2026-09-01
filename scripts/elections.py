#!/usr/bin/env python3
"""
elections.py — federal candidate data for upcoming races.

Scope, deliberately narrow: this is facts about candidates, not a
recommendation engine. No scoring, no "who matches your views." Each
candidate gets what the FEC actually reports (money) plus a short set of
hand-sourced facts (current office, background) with a citation link for
every claim, the same discipline as the rest of this site.

RACES below is a hand-maintained list. Federal candidate data has no
single clean bulk source the way incumbents do (no equivalent of the
congress-legislators roster for people who aren't in Congress yet), so
each race is added deliberately rather than scraped in bulk. Starting
with one: the 2026 Texas Senate race.

Money comes from the FEC (same pattern as fec_finance.py): total raised,
PAC vs. individual split, cash on hand. A candidate can have more than one
authorized committee (a primary committee and a separate general-election
fund); we sum across all of them so the total is complete.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

FEC_BASE = "https://api.open.fec.gov/v1"
FEC_API_KEY = os.environ.get("FEC_API_KEY", "").strip()
REQUEST_DELAY = 0.5

OUT_DIR = os.path.join("public", "elections")
INDEX = os.path.join(OUT_DIR, "index.json")

# ---------------------------------------------------------------------------
# Race configuration. Every non-FEC fact here carries its own source link,
# same rule as everywhere else on the site: no unsourced claims.
# ---------------------------------------------------------------------------
RACES: List[Dict[str, Any]] = [
    {
        "id": "tx-sen-2026",
        "office": "U.S. Senate",
        "state": "Texas",
        "stateCode": "TX",
        "electionDate": "2026-11-03",
        "seatNote": "Open seat — Sen. John Cornyn did not win renomination.",
        "sourceUrl": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Texas",
        "candidates": [
            {
                "name": "James Talarico",
                "party": "Democratic",
                "fecId": "S6TX00479",
                "committees": ["C00919084"],
                "currentOffice": "Texas House of Representatives, District 50",
                # Talarico is a sitting TX state legislator, already in our
                # state dataset — link straight to his existing record.
                "stateProfile": {"code": "TX", "chamber": "House", "district": "50"},
                "background": (
                    "Public school teacher before entering the Texas Legislature "
                    "in 2019; B.A. in Government, University of Texas at Austin; "
                    "M.Ed., Harvard University."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/James_Talarico",
                "incumbent": False,
            },
            {
                "name": "Ken Paxton",
                "party": "Republican",
                "fecId": "S6TX00388",
                "committees": ["C00901918", "C00930446"],
                "currentOffice": "Texas Attorney General",
                "stateProfile": None,
                "background": (
                    "Texas Attorney General since 2015; previously served in the "
                    "Texas House (2003-2013) and Texas Senate (2013-2015)."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Ken_Paxton",
                "incumbent": False,
            },
        ],
    },
]


class FECFetcher:
    def __init__(self, key: str):
        self.key = key
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.failures = 0

    def _get(self, path: str, params: Dict) -> Optional[Dict]:
        time.sleep(REQUEST_DELAY)
        p = dict(params); p["api_key"] = self.key
        for attempt in range(3):
            try:
                r = self.s.get(f"{FEC_BASE}{path}", params=p, timeout=(10, 30))
                if r.status_code == 429:
                    time.sleep(20 * (attempt + 1)); continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    print(f"  [fec] {path} failed: {e}", file=sys.stderr)
                    self.failures += 1
                    return None
                time.sleep(5)
        return None

    def committee_totals(self, committee_id: str) -> Optional[Dict]:
        """Totals for one committee, current cycle, falling back one cycle."""
        y = datetime.now(timezone.utc).year
        cycle = y if y % 2 == 0 else y + 1
        for c in (cycle, cycle - 2):
            data = self._get(f"/committee/{committee_id}/totals/", {"per_page": 1, "cycle": c})
            results = (data or {}).get("results") or []
            if results:
                return results[0]
        return None


def fetch_candidate_finance(fetcher: FECFetcher, committee_ids: List[str]) -> Dict[str, Any]:
    """Sum totals across every committee a candidate has authorized."""
    raised = pacs = individuals = cash = 0.0
    cycle = None
    got_any = False
    dumped = False

    for cid in committee_ids:
        t = fetcher.committee_totals(cid)
        if not t:
            continue
        got_any = True
        if not dumped:
            dumped = True
            print("  [debug] raw committee totals row:")
            print("  " + json.dumps(t, indent=2)[:700].replace("\n", "\n  "))
        raised += t.get("receipts") or 0
        pacs += (t.get("other_political_committee_contributions") or 0) + \
                (t.get("political_party_committee_contributions") or 0)
        individuals += t.get("individual_contributions") or 0
        cash = max(cash, t.get("cash_on_hand_end_period") or 0)  # most recent, not summed
        cycle = cycle or t.get("cycle")

    if not got_any:
        return {"available": False}

    denom = pacs + individuals
    return {
        "available": True,
        "cycle": cycle,
        "totalRaised": round(raised),
        "fromPacs": round(pacs),
        "fromIndividuals": round(individuals),
        "pacPct": round(pacs / denom * 100) if denom else None,
        "individualPct": round(individuals / denom * 100) if denom else None,
        "cashOnHand": round(cash),
        "source": "OpenFEC API",
    }


def build_race(fetcher: FECFetcher, race: Dict[str, Any]) -> Dict[str, Any]:
    print(f"\n=== {race['id']} ===")
    candidates = []
    for c in race["candidates"]:
        print(f"  Fetching finance for {c['name']} ({len(c['committees'])} committee[s])...")
        finance = fetch_candidate_finance(fetcher, c["committees"])
        candidates.append({
            **c,
            "financeUrl": f"https://www.fec.gov/data/candidate/{c['fecId']}/",
            "finance": finance,
        })
        raised = finance.get("totalRaised")
        print(f"    {c['name']}: {'$%d raised' % raised if raised else 'no FEC data'}")

    return {
        "id": race["id"], "office": race["office"], "state": race["state"],
        "stateCode": race["stateCode"], "electionDate": race["electionDate"],
        "seatNote": race["seatNote"], "sourceUrl": race["sourceUrl"],
        "candidates": candidates,
    }


def main():
    if not FEC_API_KEY:
        print("ERROR: FEC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    fetcher = FECFetcher(FEC_API_KEY)
    index_entries = []

    for race in RACES:
        built = build_race(fetcher, race)
        with open(os.path.join(OUT_DIR, f"{race['id']}.json"), "w") as f:
            json.dump(built, f, indent=1)
        index_entries.append({
            "id": built["id"], "office": built["office"], "state": built["state"],
            "electionDate": built["electionDate"],
            "candidates": [{"name": c["name"], "party": c["party"]} for c in built["candidates"]],
        })

    with open(INDEX, "w") as f:
        json.dump({"lastUpdated": datetime.now(timezone.utc).isoformat(),
                   "races": index_entries}, f, indent=1)

    print(f"\n--- Elections data quality ---")
    print(f"  Races built: {len(index_entries)}")
    print(f"  Failed FEC requests: {fetcher.failures}")
    print(f"Wrote {INDEX} + {len(index_entries)} race file(s)")


if __name__ == "__main__":
    main()
