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
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/James_Talarico_Press_Conference_3x4_(cropped).jpg?width=240",
                    "credit": "Antonioaesparza, CC BY-SA 4.0, via Wikimedia Commons",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:James_Talarico_Press_Conference_3x4_(cropped).jpg",
                },
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
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Ken_Paxton_2024_(3x4_cropped).jpg?width=240",
                    "credit": "Gage Skidmore, CC BY-SA 2.0, via Wikimedia Commons",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Ken_Paxton_2024_(3x4_cropped).jpg",
                },
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
    {
        "id": "ga-sen-2026",
        "office": "U.S. Senate",
        "state": "Georgia",
        "stateCode": "GA",
        "electionDate": "2026-11-03",
        "seatNote": ("Sen. Jon Ossoff (D) is seeking a second term. Georgia holds a "
                     "Dec. 1 runoff if no candidate wins a majority on Nov. 3."),
        "sourceUrl": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Georgia",
        "candidates": [
            {
                "name": "Jon Ossoff",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Jon_Ossoff_Senate_Portrait_2021_(cropped).jpg?width=240",
                    "credit": "U.S. Senate Photographic Studio, public domain",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Jon_Ossoff_Senate_Portrait_2021_(cropped).jpg",
                },
                "party": "Democratic",
                "fecId": "S8GA00180",
                "committees": ["C00718866"],
                "currentOffice": "U.S. Senator, Georgia",
                "stateProfile": None,
                "background": (
                    "U.S. senator since 2021; before politics, ran an investigative "
                    "journalism company. Seeking a second term."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Jon_Ossoff",
                "campaignSiteUrl": "https://electjon.com/bio/",
                "facts": [
                    {"label": "Born", "value": "Atlanta, Georgia"},
                    {"label": "Bachelor's", "value": "Georgetown University"},
                    {"label": "Graduate", "value": "London School of Economics"},
                    {"label": "Profession", "value": "Media executive"},
                    {"label": "Current office pay", "value": "$174,000/yr"},
                ],
                "incumbent": True,
            },
            {
                "name": "Mike Collins",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Rep._Mike_Collins_official_photo,_118th_Congress.jpg?width=240",
                    "credit": "United States Congress, public domain",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Rep._Mike_Collins_official_photo,_118th_Congress.jpg",
                },
                "party": "Republican",
                "fecId": "S6GA00390",
                "committees": ["C00544684"],
                "currentOffice": "U.S. Representative, GA-10",
                "stateProfile": None,
                "background": (
                    "U.S. representative for Georgia's 10th district since 2023; "
                    "founded a trucking company; son of former U.S. Rep. Mac Collins."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Mike_Collins_(Georgia)",
                "campaignSiteUrl": "https://mikecollinsga.com/about/",
                "facts": [
                    {"label": "Born", "value": "Jackson, Georgia"},
                    {"label": "Bachelor's", "value": "Georgia State University"},
                    {"label": "Profession", "value": "Businessman (trucking)"},
                    {"label": "Current office pay", "value": "$174,000/yr"},
                ],
                "incumbent": False,
            },
        ],
    },
    {
        "id": "mi-sen-2026",
        "office": "U.S. Senate",
        "state": "Michigan",
        "stateCode": "MI",
        "electionDate": "2026-11-03",
        "seatNote": "Open seat — Sen. Gary Peters (D) is retiring.",
        "sourceUrl": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Michigan",
        "candidates": [
            {
                "name": "Abdul El-Sayed",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Abdul_El-Sayed.jpg?width=240",
                    "credit": "Kenneth C. Zirkel, CC BY-SA 4.0, via Wikimedia Commons",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Abdul_El-Sayed.jpg",
                },
                "party": "Democratic",
                "fecId": "S6MI00418",
                "committees": ["C00902668"],
                "currentOffice": "Former Wayne County Health Director",
                "stateProfile": None,
                "background": (
                    "Physician and epidemiologist; former Detroit health commissioner "
                    "and Wayne County health director; candidate for governor in 2018."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Abdul_El-Sayed",
                "campaignSiteUrl": "https://abdulforsenate.com/priorities/",
                "facts": [
                    {"label": "Born", "value": "Southeast Michigan"},
                    {"label": "Bachelor's", "value": "University of Michigan"},
                    {"label": "Graduate", "value": "M.D., Columbia; D.Phil., Oxford (Rhodes Scholar)"},
                    {"label": "Profession", "value": "Physician & epidemiologist"},
                ],
                "incumbent": False,
            },
            {
                "name": "Mike Rogers",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Mike-Rogers-Head-Shot-2_(3x4_cropped).jpg?width=240",
                    "credit": "United States Congress, public domain",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Mike-Rogers-Head-Shot-2_(3x4_cropped).jpg",
                },
                "party": "Republican",
                "fecId": "S4MI00595",
                "committees": ["C00849810", "C00892026"],
                "currentOffice": "Former U.S. Representative, MI-08",
                "stateProfile": None,
                "background": (
                    "U.S. representative from Michigan (2001-2015), chairing the House "
                    "Intelligence Committee; former FBI special agent; Republican "
                    "nominee for this seat in 2024."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Mike_Rogers_(Michigan)",
                "campaignSiteUrl": "https://rogersforsenate.com/what-michiganders-need-to-know",
                "facts": [
                    {"label": "Born", "value": "Livonia, Michigan"},
                    {"label": "Bachelor's", "value": "Adrian College"},
                    {"label": "Profession", "value": "Former FBI special agent"},
                ],
                "incumbent": False,
            },
        ],
    },
    {
        "id": "nc-sen-2026",
        "office": "U.S. Senate",
        "state": "North Carolina",
        "stateCode": "NC",
        "electionDate": "2026-11-03",
        "seatNote": "Open seat — Sen. Thom Tillis (R) is not seeking a third term.",
        "sourceUrl": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_North_Carolina",
        "candidates": [
            {
                "name": "Roy Cooper",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Gov._Cooper_Cropped.jpg?width=240",
                    "credit": "via Wikimedia Commons",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Gov._Cooper_Cropped.jpg",
                },
                "party": "Democratic",
                "fecId": "S6NC00407",
                "committees": ["C00913566"],
                "currentOffice": "Former Governor of North Carolina",
                "stateProfile": None,
                "background": (
                    "Governor of North Carolina (2017-2025); state attorney "
                    "general (2001-2017); previously a state legislator."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Roy_Cooper",
                "campaignSiteUrl": "https://roycooper.com/about/",
                "facts": [
                    {"label": "Born", "value": "Nashville, North Carolina"},
                    {"label": "Bachelor's", "value": "University of North Carolina at Chapel Hill"},
                    {"label": "Graduate", "value": "J.D., University of North Carolina"},
                    {"label": "Profession", "value": "Attorney"},
                ],
                "incumbent": False,
            },
            {
                "name": "Michael Whatley",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Michael_Whatley_(54351730621)_(cropped).jpg?width=240",
                    "credit": "Gage Skidmore, CC BY-SA 2.0, via Wikimedia Commons",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Michael_Whatley_(54351730621)_(cropped).jpg",
                },
                "party": "Republican",
                "fecId": "S6NC00415",
                "committees": ["C00913996", "C00909416"],
                "currentOffice": "Former RNC Chairman",
                "stateProfile": None,
                "background": (
                    "Chair of the Republican National Committee (2024-2025) and "
                    "the North Carolina Republican Party (2019-2024); attorney; "
                    "has not previously held elected office."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Michael_Whatley",
                "campaignSiteUrl": "https://michaelwhatley.com/issues/",
                "facts": [
                    {"label": "Born", "value": "North Carolina"},
                    {"label": "Bachelor's", "value": "UNC Charlotte"},
                    {"label": "Graduate", "value": "M.A., Wake Forest; M.A. & J.D., Notre Dame"},
                    {"label": "Profession", "value": "Attorney"},
                ],
                "incumbent": False,
            },
        ],
    },
    {
        "id": "me-sen-2026",
        "office": "U.S. Senate",
        "state": "Maine",
        "stateCode": "ME",
        "electionDate": "2026-11-03",
        "seatNote": ("Sen. Susan Collins (R) is seeking a sixth term. Primary winner "
                     "Graham Platner withdrew in July; Maine Democrats nominated Troy "
                     "Jackson at a special convention on July 25."),
        "sourceUrl": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Maine",
        "candidates": [
            {
                "name": "Troy Jackson",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Senate_President_Troy_Jackson_(cropped).png?width=240",
                    "credit": "ArenLeBrun, via Wikimedia Commons",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Senate_President_Troy_Jackson_(cropped).png",
                },
                "party": "Democratic",
                "fecId": "S6ME00464",
                "committees": ["C00955609"],
                "currentOffice": "Former Maine Senate President",
                "stateProfile": None,
                "background": (
                    "Fifth-generation logger from northern Maine; served in the "
                    "Maine Senate 2008-2014 and 2016-2024, as its president from "
                    "2018 to 2024; candidate for governor earlier in 2026."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Troy_Jackson_(Maine)",
                "financeNote": "Committee registered July 2026; its first FEC report is due Oct. 15, 2026.",
                "campaignSiteUrl": "https://www.jacksonformaine.com/priorities",
                "facts": [
                    {"label": "Profession", "value": "Logger"},
                ],
                "incumbent": False,
            },
            {
                "name": "Susan Collins",
                "photo": {
                    "url": "https://commons.wikimedia.org/wiki/Special:FilePath/Senator_Susan_Collins_2014_official_portrait.jpg?width=240",
                    "credit": "U.S. Congress, public domain",
                    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Senator_Susan_Collins_2014_official_portrait.jpg",
                },
                "party": "Republican",
                "fecId": "S6ME00159",
                "committees": ["C00314575"],
                "currentOffice": "U.S. Senator, Maine",
                "stateProfile": None,
                "background": (
                    "U.S. senator since 1997; chairs the Senate Appropriations "
                    "Committee. Seeking a sixth term."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Susan_Collins_(Maine)",
                "campaignSiteUrl": "https://susancollins.com/track-record/",
                "facts": [
                    {"label": "Born", "value": "Caribou, Maine"},
                    {"label": "Bachelor's", "value": "St. Lawrence University"},
                    {"label": "Current office pay", "value": "$174,000/yr"},
                ],
                "incumbent": True,
            },
        ],
    },
    {
        "id": "sc-sen-2026",
        "office": "U.S. Senate",
        "state": "South Carolina",
        "stateCode": "SC",
        "electionDate": "2026-11-03",
        "seatNote": ("Sen. Lindsey Graham (R) died July 11. Gov. Henry McMaster "
                     "appointed Darline Graham, his sister, to the seat; she won the "
                     "Aug. 25 special primary runoff to seek a full term."),
        "sourceUrl": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_South_Carolina",
        "candidates": [
            {
                "name": "Annie Andrews",
                "party": "Democratic",
                "fecId": "S6SC04239",
                "committees": ["C00906024"],
                "currentOffice": "Pediatrician",
                "stateProfile": None,
                "background": (
                    "Pediatrician who spent 15 years on the faculty of the Medical "
                    "University of South Carolina; Democratic nominee for a U.S. "
                    "House seat in 2022."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Annie_Andrews",
                "facts": [
                    {"label": "Born", "value": "Paducah, Kentucky"},
                    {"label": "Profession", "value": "Pediatrician"},
                ],
                "campaignSiteUrl": "https://drannieandrews.com/platform/",
                "incumbent": False,
            },
            {
                "name": "Darline Graham",
                "party": "Republican",
                "fecId": "",  # committee registered Aug 2026; ID pending FEC indexing
                "committees": [],
                "currentOffice": "U.S. Senator, South Carolina (appointed)",
                "stateProfile": None,
                "background": (
                    "Appointed to the Senate in July 2026 to fill the seat of her "
                    "late brother, Sen. Lindsey Graham; her first elected office. "
                    "Won the Aug. 25 special Republican primary runoff."
                ),
                "backgroundSourceUrl": "https://ballotpedia.org/Darline_Graham",
                "financeNote": "Committee registered August 2026; its first FEC report is due Oct. 15, 2026.",
                "facts": [
                    {"label": "Profession", "value": "Public administrator"},
                    {"label": "Current office pay", "value": "$174,000/yr"},
                ],
                "campaignSiteUrl": "https://www.darlinegraham.com/#record",
                "incumbent": True,
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
    donor_ids: Dict[str, str] = {}  # contributor name -> that committee's own FEC ID
    dumped = False

    for cid in committee_ids:
        params: Dict[str, Any] = {
            "committee_id": cid,
            "two_year_transaction_period": cycle,
            "contributor_type": "committee",
            "per_page": 100,
            # Largest receipts first: with a page cap, date order can surface
            # small recent checks while burying major PAC money (verified
            # sortable field in the FEC API's own source).
            "sort": "-contribution_receipt_amount",
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
                    # Schedule A reports the donor committee's own FEC ID --
                    # an exact identifier, so the chip can link straight to
                    # that committee's page on fec.gov. No name matching.
                    if name not in donor_ids and row.get("contributor_id"):
                        donor_ids[name] = row["contributor_id"]
            last = (data.get("pagination") or {}).get("last_indexes") or {}
            if not results or not last:
                break  # no more pages
            params = {**params, **last}  # seek pagination: echo cursor back

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:TOP_PAC_DONORS]
    out = []
    for name, amt in ranked:
        item: Dict[str, Any] = {"name": name, "amount": round(amt)}
        if name in donor_ids:
            item["committeeId"] = donor_ids[name]
            item["fecUrl"] = f"https://www.fec.gov/data/committee/{donor_ids[name]}/"
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Donor committee classification, straight from the FEC's own taxonomy
# (designation / committee_type / organization_type on /committee/{id}/).
# Neutral, factual labels: "corporate PAC" vs "leadership PAC" vs "candidate
# committee" is exactly the distinction voters care about, and it comes from
# the FEC's classification of the committee, not from us.
# ---------------------------------------------------------------------------
def _kind_label(info: Dict[str, Any]) -> str:
    desig = (info.get("designation") or "").upper()
    ctype = (info.get("committee_type") or "").upper()
    orgt = (info.get("organization_type") or "").upper()
    if desig == "J":
        return "joint fundraising"
    if desig == "D":
        return "leadership PAC"
    if desig in ("P", "A"):
        return "candidate committee"
    if ctype in ("X", "Y", "Z"):
        return "party committee"
    if ctype == "O":
        return "super PAC"
    if orgt in ("C", "W"):
        return "corporate PAC"
    if orgt == "L":
        return "labor union PAC"
    if orgt == "T":
        return "trade assoc. PAC"
    if orgt == "M":
        return "membership org PAC"
    if orgt == "V":
        return "co-op PAC"
    return "PAC"


def classify_donor_committees(fetcher: "FECFetcher", donors: List[Dict[str, Any]],
                              cache: Dict[str, Optional[str]]) -> None:
    """Annotate donor dicts in place with the FEC's classification of each
    donor committee, looked up by exact committee ID (no name matching)."""
    for d in donors:
        cid = d.get("committeeId")
        if not cid:
            continue
        if cid not in cache:
            data = fetcher._get(f"/committee/{cid}/", {})
            results = (data or {}).get("results") or []
            cache[cid] = _kind_label(results[0]) if results else None
        if cache.get(cid):
            d["kind"] = cache[cid]


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
               kind_cache: Dict[str, Optional[str]]) -> Dict[str, Any]:
    print(f"\n=== {race['id']} ===")
    candidates = []
    for c in race["candidates"]:
        print(f"  Fetching finance for {c['name']} ({len(c['committees'])} committee[s])...")
        finance = fetch_candidate_finance(fetcher, c["committees"])
        top_pacs = fetch_top_pac_donors(fetcher, c["committees"])
        classify_donor_committees(fetcher, top_pacs, kind_cache)
        kinds = sum(1 for d in top_pacs if d.get("kind"))
        print(f"    {c['name']}: {len(top_pacs)} named PAC donors found, "
              f"{kinds} classified by FEC committee type")
        candidates.append({
            **c,
            "financeUrl": (f"https://www.fec.gov/data/candidate/{c['fecId']}/"
                           if c.get("fecId") else None),
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
    kind_cache: Dict[str, Optional[str]] = {}

    for race in RACES:
        built = build_race(fetcher, race, kind_cache)
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
