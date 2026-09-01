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

Named PAC donors -- e.g. "did this candidate take AIPAC money" -- come from
the itemized /schedules/schedule_a/ endpoint, filtered to
contributor_type=committee, aggregated by contributor name on our side.
(The old /schedules/schedule_a/by_contributor/ aggregate endpoint no longer
exists in the API -- the only surviving by_contributor route is for
inaugural committees -- so the earlier 422/candidate_id theory is moot; the
path itself is gone.) We keep only Form 3 lines 11B (party committees) and
11C (other political committees, i.e. PACs) so that transfers from a
candidate's own joint-fundraising committees (line 12) don't get miscounted
as "donors". We report whatever names come back rather than pre-filtering
to any org we expect to see.

Note on field names: /committee/{id}/totals/ reports cash on hand as
`last_cash_on_hand_end_period`. The unprefixed `cash_on_hand_end_period`
only exists on the /reports/ endpoints -- reading the wrong one silently
yields None and looks like "no data".
"""

import os
import re
import sys
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

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
                "facts": [
                    {"label": "Born", "value": "Round Rock, Texas"},
                    {"label": "High school", "value": "McNeil High School"},
                    {"label": "Bachelor's", "value": "University of Texas at Austin"},
                    {"label": "Graduate", "value": "Harvard University"},
                    {"label": "Profession", "value": "Educator"},
                    {"label": "Current office pay", "value": "$7,200/yr + $221/day per diem"},
                ],
                "campaignSiteUrl": "https://jamestalarico.com/issues/",
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
                "facts": [
                    {"label": "Born", "value": "Minot, North Dakota"},
                    {"label": "Bachelor's", "value": "Baylor University"},
                    {"label": "Graduate", "value": "M.B.A., Baylor; J.D., University of Virginia"},
                    {"label": "Profession", "value": "Attorney"},
                    {"label": "Current office pay", "value": "$153,750/yr"},
                ],
                "campaignSiteUrl": "https://www.kenpaxton.com/issues",
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
            # Sort so we get the latest coverage period explicitly -- an
            # unsorted "first row" can be an early or amended filing with a
            # stale/zero cash figure, the same failure mode we hit before on
            # the candidate-level totals endpoint.
            data = self._get(f"/committee/{committee_id}/totals/",
                             {"per_page": 1, "cycle": c, "sort": "-coverage_end_date"})
            results = (data or {}).get("results") or []
            # Totals rows name this field `last_cash_on_hand_end_period`
            # (NOT `cash_on_hand_end_period`, which is a /reports/ field).
            if results and results[0].get("last_cash_on_hand_end_period") is not None:
                return results[0]
        return None



TOP_PAC_DONORS = 8  # named PACs to surface per candidate


MAX_SCHED_A_PAGES = 15  # per committee; 100 rows/page = 1,500 receipts, plenty for committee-type receipts

# Form 3 receipt lines we count as "donors": 11B = party committees,
# 11C = other political committees (PACs). Excludes 11A (individuals),
# 12 (transfers from the candidate's own authorized/joint committees).
DONOR_LINES = {"11B", "11C"}


def fetch_top_pac_donors(fetcher: "FECFetcher", committee_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Aggregate itemized Schedule A receipts from committee-type contributors,
    across all of a candidate's committees, for the current cycle. Uses the
    itemized endpoint (the by_contributor aggregate was removed from the API)
    with its seek-style pagination: each page's `pagination.last_indexes`
    values are echoed back as params to get the next page. Returns [] rather
    than raising if anything is unavailable -- a transparency page should
    never show a wrong number, only a missing one.
    """
    y = datetime.now(timezone.utc).year
    cycle = y if y % 2 == 0 else y + 1
    totals: Dict[str, float] = {}
    dumped = False

    for cid in committee_ids:
        params: Dict[str, Any] = {
            "committee_id": cid,
            "two_year_transaction_period": cycle,
            "contributor_type": "committee",
            "per_page": 100,
        }
        for _page in range(MAX_SCHED_A_PAGES):
            data = fetcher._get("/schedules/schedule_a/", params)
            if data is None:
                break  # request failed after retries; keep whatever we have
            results = data.get("results") or []
            if not dumped and results:
                dumped = True
                print("  [debug] raw itemized schedule_a row:")
                snippet = json.dumps(results[0], indent=2)[:500]
                print("  " + snippet.replace(chr(10), chr(10) + "  "))
            for row in results:
                line = (row.get("line_number") or "").strip().upper()
                if line and line not in DONOR_LINES:
                    continue  # skip transfers (12), earmarks, refunds, etc.
                name = (row.get("contributor_name") or "").strip()
                amt = row.get("contribution_receipt_amount") or 0
                if name and amt > 0:
                    totals[name] = totals.get(name, 0) + amt
            last = (data.get("pagination") or {}).get("last_indexes") or {}
            if not results or not last:
                break  # no more pages
            params = {**params, **last}  # seek pagination: echo cursor back

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:TOP_PAC_DONORS]
    return [{"name": name, "amount": round(amt)} for name, amt in ranked]


# ---------------------------------------------------------------------------
# FEC enforcement history for donor committees.
#
# The FEC's own legal-search API (/legal/search/?type=murs) counts Matters
# Under Review where a name appears as a RESPONDENT (the party the matter was
# against). That's an official, factual record -- deliberately NOT a
# "nefarious" score. We attach the count plus a link to the FEC's search so
# readers can see the actual cases; we make no judgment about them (matters
# include settled, dismissed, and decades-old cases).
#
# Matching is by name-as-reported on Schedule A. IMPORTANT: the API's
# case_respondents filter word-OR-matches by default (the word "COMMITTEE"
# alone matches thousands of cases), so every query MUST be a quoted phrase.
# Reported names are often mashups ("X COMMITTEE (EPEC)/SOME UNION"), so we
# split on separators and search each segment as its own phrase, keeping the
# best match. Counts above SANITY_CAP are discarded as bad matches. Phrase
# matching can still undercount when a committee donates under an acronym;
# undercounting is acceptable -- the display simply omits the tag. Better a
# missing number than a wrong one.
# ---------------------------------------------------------------------------
SANITY_CAP = 100  # no single committee has this many MURs; above = bad match


def _name_phrases(name: str) -> List[str]:
    """Split a reported contributor name into searchable org-name phrases."""
    cleaned = re.sub(r"\([^)]*\)", " ", name)          # drop parentheticals: (EPEC)
    parts = re.split(r"[/;]| - ", cleaned)             # split glued-together names
    phrases = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip(" ,.")
        if len(p) >= 8 and p not in phrases:           # skip fragments/acronyms
            phrases.append(p)
    return phrases[:3]


def fetch_enforcement_counts(fetcher: "FECFetcher", donors: List[Dict[str, Any]],
                             cache: Dict[str, Optional[int]]) -> None:
    """Annotate donor dicts in place with FEC MUR respondent counts."""
    for d in donors:
        best_count, best_phrase = 0, None
        for phrase in _name_phrases(d["name"]):
            if phrase not in cache:
                data = fetcher._get("/legal/search/",
                                    {"type": "murs",
                                     "case_respondents": f'"{phrase}"',  # exact phrase
                                     "hits_returned": 1})
                if data is None:
                    continue  # request failed; don't cache
                n = int(data.get("total_murs") or 0)
                if n > SANITY_CAP:
                    print(f"  [warn] enforcement match for '{phrase}' returned {n} "
                          f"-- discarding as a bad match", file=sys.stderr)
                    n = 0
                cache[phrase] = n
            if (cache.get(phrase) or 0) > best_count:
                best_count, best_phrase = cache[phrase], phrase
        if best_count > 0:
            d["fecMurs"] = best_count
            d["fecMursUrl"] = ("https://www.fec.gov/data/legal/search/enforcement/"
                               "?case_respondents=" + quote_plus(f'"{best_phrase}"'))


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
        cash = max(cash, t.get("last_cash_on_hand_end_period") or 0)  # most recent, not summed
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


def build_race(fetcher: FECFetcher, race: Dict[str, Any],
               enforcement_cache: Dict[str, int]) -> Dict[str, Any]:
    print(f"\n=== {race['id']} ===")
    candidates = []
    for c in race["candidates"]:
        print(f"  Fetching finance for {c['name']} ({len(c['committees'])} committee[s])...")
        finance = fetch_candidate_finance(fetcher, c["committees"])
        top_pacs = fetch_top_pac_donors(fetcher, c["committees"])
        fetch_enforcement_counts(fetcher, top_pacs, enforcement_cache)
        flagged = sum(1 for d in top_pacs if d.get("fecMurs"))
        print(f"    {c['name']}: {len(top_pacs)} named PAC donors found, "
              f"{flagged} with FEC enforcement history")
        candidates.append({
            **c,
            "financeUrl": f"https://www.fec.gov/data/candidate/{c['fecId']}/",
            "finance": finance,
            "topPacDonors": top_pacs,
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
    any_finance = False
    enforcement_cache: Dict[str, int] = {}

    for race in RACES:
        built = build_race(fetcher, race, enforcement_cache)
        if any(c["finance"].get("available") for c in built["candidates"]):
            any_finance = True
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

    # If literally no candidate got finance data AND we saw request failures,
    # something is systemically wrong (bad key, endpoint change, outage).
    # Exit non-zero so the workflow's commit step never runs and yesterday's
    # good data stays live. An empty page is better than a wrong one; stale
    # is better than empty.
    if fetcher.failures and not any_finance:
        print("ERROR: zero candidates have finance data and there were "
              "request failures — refusing to publish an all-empty dataset.",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
