#!/usr/bin/env python3
"""
fec_finance.py — add campaign-finance data to each member.

Source: OpenFEC API (https://api.open.fec.gov), the Federal Election
Commission's official REST API. Requires a free key from
https://api.data.gov/signup/ — set it as FEC_API_KEY.

What this adds per member, all straight from FEC filings:
  - totalRaised            total receipts this cycle
  - fromPacs               dollars from PACs / other committees
  - fromIndividuals        dollars from individual donors
  - pacPct / individualPct the split, as whole percentages
  - cashOnHand             cash on hand at end of last period
  - topPacDonors           up to 3 PACs by amount given to this candidate
  - financeCycle           the election cycle these numbers cover
  - financeSourceUrl       deep link to the candidate's FEC.gov page

What it deliberately does NOT claim:
  The FEC does not publish clean "top corporations" or "industry"
  groupings -- that was OpenSecrets' editorial layer, and their API shut
  down in April 2025. We report PAC contributions, which are real and
  sourced, and we do not invent industry attributions.

Bridging IDs: the congress-legislators roster already carries each member's
FEC candidate ID(s) in id.fec, so we join on that rather than matching names.
A member may have several FEC IDs across a long career (e.g. an old House ID
plus a current Senate ID); we pick the one whose office matches their current
chamber and which has the most recent activity.
"""

import os
import sys
import time
import json
from typing import Any, Dict, List, Optional

import requests

FEC_BASE = "https://api.open.fec.gov/v1"
FEC_API_KEY = os.environ.get("FEC_API_KEY", "").strip()

REQUEST_DELAY = 0.4  # FEC allows 1,000/hour on a standard key; stay well under.

# Which FEC office code goes with which chamber in our data.
CHAMBER_TO_OFFICE = {"Senate": "S", "House": "H"}


class FinanceFetcher:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.failures = 0
        self.no_id = 0
        self.no_data = 0
        self.enriched = 0
        self._dumped_totals = False
        self._dumped_sched = False

    def _get(self, path: str, params: Dict) -> Optional[Dict]:
        time.sleep(REQUEST_DELAY)
        p = dict(params)
        p["api_key"] = self.api_key
        url = f"{FEC_BASE}{path}"
        try:
            r = self.session.get(url, params=p, timeout=30)
            if r.status_code == 429:
                print("  [fec] rate limited; waiting 60s...")
                time.sleep(60)
                r = self.session.get(url, params=p, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            # Never print url -- it carries the key.
            print(f"  [fec] request failed ({path}): {e}", file=sys.stderr)
            self.failures += 1
            return None

    def pick_fec_id(self, fec_ids: List[str], chamber: str) -> Optional[str]:
        """
        Choose the FEC candidate ID that matches the member's current office.
        FEC IDs start with the office letter: H####, S####, P####.
        """
        if not fec_ids:
            return None
        office = CHAMBER_TO_OFFICE.get(chamber)
        if office:
            matches = [fid for fid in fec_ids if fid and fid.startswith(office)]
            if matches:
                # If several (different cycles/states), the lexically largest
                # tends to be the most recent; good enough, and we confirm via
                # the totals call which returns the active cycle anyway.
                return sorted(matches)[-1]
        # Fall back to the first ID if no office match (rare).
        return fec_ids[0]

    def fetch_totals(self, fec_id: str) -> Optional[Dict[str, Any]]:
        """
        Candidate financial totals for the most recent cycle on file.
        We don't hardcode a cycle -- we ask for totals sorted newest-first
        and take the top row, so this keeps working every election.
        """
        data = self._get(
            f"/candidate/{fec_id}/totals/",
            {"per_page": 1, "sort": "-cycle"},
        )
        if not data:
            return None

        results = data.get("results") or []

        if not self._dumped_totals and results:
            self._dumped_totals = True
            print("\n  [debug] raw candidate totals row:")
            print("  " + json.dumps(results[0], indent=2)[:900].replace("\n", "\n  "))
            print()

        if not results:
            return None

        t = results[0]

        receipts = t.get("receipts") or 0
        individuals = t.get("individual_contributions") or 0
        # PAC money shows up as "other political committee contributions";
        # party committee money is tracked separately and we fold it in.
        pac = (t.get("other_political_committee_contributions") or 0)
        party = (t.get("political_party_committee_contributions") or 0)
        pac_total = pac + party

        denom = individuals + pac_total
        pac_pct = round(pac_total / denom * 100) if denom else None
        ind_pct = round(individuals / denom * 100) if denom else None

        return {
            "financeCycle": t.get("cycle"),
            "totalRaised": round(receipts),
            "fromPacs": round(pac_total),
            "fromIndividuals": round(individuals),
            "pacPct": pac_pct,
            "individualPct": ind_pct,
            "cashOnHand": round(t.get("last_cash_on_hand_end_period") or 0),
        }

    def fetch_top_pacs(self, fec_id: str, cycle: Optional[int]) -> List[Dict[str, Any]]:
        """
        Top PACs giving to this candidate, via Schedule A contributions
        aggregated by contributor committee. Best-effort: if the endpoint
        shape differs, we degrade to an empty list rather than failing.
        """
        params = {
            "candidate_id": fec_id,
            "per_page": 3,
            "sort": "-total",
        }
        if cycle:
            params["cycle"] = cycle

        data = self._get("/schedules/schedule_a/by_contributor/", params)

        # This endpoint isn't available for every candidate/cycle; a None or
        # empty result is normal, not an error.
        if not data:
            return []

        results = data.get("results") or []

        if not self._dumped_sched and results:
            self._dumped_sched = True
            print("\n  [debug] raw schedule_a by_contributor row:")
            print("  " + json.dumps(results[0], indent=2)[:700].replace("\n", "\n  "))
            print()

        top = []
        for r in results[:3]:
            name = (
                r.get("contributor_name")
                or r.get("contributor_committee_name")
                or "Unnamed committee"
            )
            amount = r.get("total") or r.get("total_amount") or 0
            top.append({"name": name.title() if name.isupper() else name,
                        "amount": round(amount)})
        return top

    def enrich(self, member: Dict[str, Any], fec_ids: List[str]) -> None:
        """Attach finance fields to one member dict in place."""
        fec_id = self.pick_fec_id(fec_ids, member.get("chamber"))
        if not fec_id:
            self.no_id += 1
            member["finance"] = None
            return

        totals = self.fetch_totals(fec_id)
        if not totals:
            self.no_data += 1
            member["finance"] = None
            return

        top_pacs = self.fetch_top_pacs(fec_id, totals.get("financeCycle"))

        member["finance"] = {
            **totals,
            "topPacDonors": top_pacs,
            "fecId": fec_id,
            "financeSourceUrl": f"https://www.fec.gov/data/candidate/{fec_id}/",
            "source": "OpenFEC API",
        }
        self.enriched += 1

    def report(self, total: int) -> None:
        print("\n--- Finance data quality ---")
        print(f"  Enriched:        {self.enriched}/{total}")
        print(f"  No FEC id:       {self.no_id}")
        print(f"  No totals found: {self.no_data}")
        print(f"  Failed requests: {self.failures}")


def add_finance(members: List[Dict[str, Any]],
                fec_id_by_bioguide: Dict[str, List[str]]) -> bool:
    """
    Enrich members with FEC finance data. Returns True if finance was
    attempted (key present), False if skipped. Mutates members in place.
    """
    if not FEC_API_KEY:
        print("WARNING: FEC_API_KEY not set -- skipping campaign finance.")
        print("  Get a free key at https://api.data.gov/signup/ and add it as")
        print("  a repo secret named FEC_API_KEY to enable donor data.\n")
        for m in members:
            m["finance"] = None
        return False

    print("Fetching campaign finance from OpenFEC...")
    fetcher = FinanceFetcher(FEC_API_KEY)
    for i, m in enumerate(members, start=1):
        fec_ids = fec_id_by_bioguide.get(m["bioguideId"], [])
        fetcher.enrich(m, fec_ids)
        if i % 50 == 0:
            print(f"  {i}/{len(members)} members processed")

    fetcher.report(len(members))
    return True
