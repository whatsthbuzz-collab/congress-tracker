#!/usr/bin/env python3
"""
votes.py — add federal HOUSE roll-call voting behavior to each member.

Source: the official Congress.gov beta "House Roll Call Votes" endpoints
(https://api.congress.gov/v3/house-vote/...), released 2025 in partnership
with the Office of the Clerk. Uses the SAME CONGRESS_API_KEY already set for
bills. No new secret.

  List:    /house-vote/{congress}/{session}
  Members: /house-vote/{congress}/{session}/{voteNumber}/members
           -> how each Representative voted, keyed by Bioguide ID.

IMPORTANT SCOPE LIMIT: these endpoints are HOUSE ONLY. The Senate does not yet
publish roll-call votes through the Congress.gov API (expected in a later
phase). So senators get voting == None, and the UI labels the column
"House only" so the gap is honest rather than looking broken.

Because the API default response is XML, every call explicitly requests
format=json.

Per Representative we compute:
  - partyLinePct    % of party-split votes where they sided with their party
  - missedPct       % of eligible votes they missed ("Not Voting")
  - votesTotal      how many roll calls we evaluated them on
  - recentVotes     up to N most recent votes with their individual position

The party-line definition matches the honest one we use elsewhere: for each
vote, find each major party's majority position; a member is "with party" when
their Yea/Nay matches their own party's majority. Missed votes and votes with
no clear party majority are excluded from the party-line denominator.
"""

import os
import sys
import json
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://api.congress.gov/v3"
API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()

# Most recent roll calls to analyze. The House takes ~500-700 votes per
# Congress; we pull the most recent CAP for a current picture. Each vote costs
# 1 list slot + 1 members call.
VOTE_CAP = 150

RECENT_PER_MEMBER = 10
REQUEST_DELAY = 0.3  # shares the Congress.gov budget with bills; be polite

# Vote position strings the House API uses. We normalize a few variants.
YEA_SET = {"Yea", "Aye", "Yes"}
NAY_SET = {"Nay", "No"}
MISSED_SET = {"Not Voting", "Present"}  # Present isn't "missed" but isn't Y/N


class HouseVoteFetcher:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.failures = 0
        self._dumped_list = False
        self._dumped_members = False

    def _get(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        time.sleep(REQUEST_DELAY)
        p = dict(params or {})
        p["api_key"] = self.api_key
        p["format"] = "json"  # API defaults to XML; we always want JSON.
        url = f"{API_BASE}{path}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=p, timeout=30)
                if r.status_code == 429:
                    wait = 20 * (attempt + 1)
                    print(f"  [votes] rate limited; waiting {wait}s "
                          f"(attempt {attempt + 1}/3)")
                    time.sleep(wait)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    print(f"  [votes] request failed ({path}): {e}",
                          file=sys.stderr)
                    self.failures += 1
                    return None
                time.sleep(5)
        return None

    def list_votes(self, congress: int, session: int) -> List[Dict]:
        """List roll-call votes for a chamber-session, most recent first."""
        data = self._get(
            f"/house-vote/{congress}/{session}",
            {"limit": 250, "sort": "updateDate+desc"},
        )
        if not data:
            return []

        if not self._dumped_list:
            self._dumped_list = True
            print("\n  [debug] house-vote list response keys:", list(data.keys()))
            # The list container name varies; find the list of votes.
            for k, v in data.items():
                if isinstance(v, list) and v:
                    print(f"  [debug] first item in '{k}':",
                          json.dumps(v[0], indent=2)[:500].replace("\n", "\n  "))
                    break
            print()

        # Find whichever key holds the list of votes.
        votes = None
        for k in ("houseRollCallVotes", "votes", "houseVotes", "results"):
            if isinstance(data.get(k), list):
                votes = data[k]
                break
        if votes is None:
            # Fall back: first list-valued field.
            for v in data.values():
                if isinstance(v, list):
                    votes = v
                    break
        return votes or []

    def fetch_member_votes(self, congress: int, session: int,
                           vote_number: int) -> Optional[Dict]:
        """Get each Representative's position on one roll call."""
        data = self._get(
            f"/house-vote/{congress}/{session}/{vote_number}/members"
        )
        if not data:
            return None

        if not self._dumped_members:
            self._dumped_members = True
            print("\n  [debug] house-vote members response keys:",
                  list(data.keys()))
            print("  " + json.dumps(data, indent=2)[:800].replace("\n", "\n  "))
            print()

        return data


def _extract_member_positions(members_payload: Dict) -> List[Dict]:
    """
    Normalize the members-level response into a list of
    {bioguide, position, party} regardless of the exact container names,
    since this is a beta endpoint whose shape may shift.
    """
    # Drill to the list of member-vote records.
    candidates = []

    def walk(obj):
        if isinstance(obj, list):
            # A list of dicts that look like member votes?
            if obj and isinstance(obj[0], dict) and any(
                key in obj[0] for key in ("bioguideID", "bioguideId", "voteCast",
                                          "voteState", "voteParty")
            ):
                candidates.append(obj)
            else:
                for item in obj:
                    walk(item)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)

    walk(members_payload)

    records = []
    for lst in candidates:
        for m in lst:
            if not isinstance(m, dict):
                continue
            bid = m.get("bioguideID") or m.get("bioguideId") or m.get("bioguide")
            pos = (m.get("voteCast") or m.get("vote") or m.get("position")
                   or m.get("voteState"))
            party = m.get("voteParty") or m.get("party")
            if bid and pos:
                records.append({
                    "bioguide": bid,
                    "position": pos,
                    "party": (party or "")[:1].upper(),  # D/R/I
                })
    return records


def _norm_position(pos: str) -> str:
    if pos in YEA_SET:
        return "Yea"
    if pos in NAY_SET:
        return "Nay"
    if pos == "Not Voting":
        return "Not Voting"
    if pos == "Present":
        return "Present"
    return pos


def _majority(records: List[Dict], party_letter: str) -> Optional[str]:
    counts = Counter(
        _norm_position(r["position"]) for r in records
        if r["party"] == party_letter
        and _norm_position(r["position"]) in ("Yea", "Nay")
    )
    yea, nay = counts.get("Yea", 0), counts.get("Nay", 0)
    if yea == nay:
        return None
    return "Yea" if yea > nay else "Nay"


def add_votes(members: List[Dict[str, Any]], congress: int) -> bool:
    """
    Enrich HOUSE members with voting behavior from Congress.gov. Senators get
    voting == None (labeled in the UI). Mutates members in place.
    """
    if not API_KEY:
        print("WARNING: CONGRESS_API_KEY not set -- skipping votes.")
        for m in members:
            m["voting"] = None
        return False

    print(f"Fetching House roll-call votes (Congress {congress})...")
    fetcher = HouseVoteFetcher(API_KEY)

    # Gather recent votes across both sessions of the current Congress.
    vote_refs: List[Dict] = []
    for session in (2, 1):  # session 2 is more recent; take it first
        listed = fetcher.list_votes(congress, session)
        for v in listed:
            num = (v.get("rollCallNumber") or v.get("voteNumber")
                   or v.get("number") or v.get("rollCall"))
            if num is not None:
                vote_refs.append({
                    "session": session,
                    "number": int(num),
                    "date": (v.get("startDate") or v.get("updateDate")
                             or v.get("date") or "")[:10],
                    "result": v.get("result") or v.get("voteResult") or "",
                    "question": (v.get("voteQuestion") or v.get("question")
                                 or v.get("legislationType", "")),
                    "bill": _bill_label(v),
                    "billUrl": _bill_url(v),
                })
        if len(vote_refs) >= VOTE_CAP:
            break

    # Keep the most recent VOTE_CAP by date.
    vote_refs.sort(key=lambda r: r["date"], reverse=True)
    vote_refs = vote_refs[:VOTE_CAP]

    if not vote_refs:
        print("  No House votes retrieved. Leaving vote fields empty.")
        print(f"  Failed requests: {fetcher.failures}")
        for m in members:
            m["voting"] = None
        return False

    print(f"  Analyzing {len(vote_refs)} House roll-call votes.")

    by_bioguide = {m["bioguideId"]: m for m in members}
    tally = {bid: {"with": 0, "against": 0, "missed": 0,
                   "eligible": 0, "recent": []}
             for bid in by_bioguide}

    for ref in vote_refs:
        payload = fetcher.fetch_member_votes(congress, ref["session"],
                                             ref["number"])
        if not payload:
            continue
        records = _extract_member_positions(payload)
        if not records:
            continue

        dem_maj = _majority(records, "D")
        rep_maj = _majority(records, "R")
        maj_by_party = {"D": dem_maj, "R": rep_maj}

        meta = {
            "date": ref["date"],
            "question": ref["question"],
            "result": ref["result"],
            "chamber": "House",
        }
        if ref["bill"]:
            meta["bill"] = ref["bill"]
        if ref["billUrl"]:
            meta["billUrl"] = ref["billUrl"]

        for rec in records:
            bid = rec["bioguide"]
            t = tally.get(bid)
            if t is None:
                continue
            pos = _norm_position(rec["position"])
            t["eligible"] += 1
            if pos == "Not Voting":
                t["missed"] += 1
            elif pos in ("Yea", "Nay"):
                pl = maj_by_party.get(rec["party"])
                if pl is not None:
                    if pos == pl:
                        t["with"] += 1
                    else:
                        t["against"] += 1
            if len(t["recent"]) < RECENT_PER_MEMBER:
                t["recent"].append({**meta, "position": pos})

    enriched = 0
    for bid, m in by_bioguide.items():
        t = tally[bid]
        if t["eligible"] == 0:
            m["voting"] = None
            continue
        partisan = t["with"] + t["against"]
        m["voting"] = {
            "partyLinePct": round(t["with"] / partisan * 100) if partisan else None,
            "missedPct": round(t["missed"] / t["eligible"] * 100),
            "votesTotal": t["eligible"],
            "votesWithParty": t["with"],
            "votesAgainstParty": t["against"],
            "recentVotes": t["recent"],
            "chamberScope": "House",
            "source": "Congress.gov House Roll Call Votes API (beta)",
            "sourceUrl": "https://www.congress.gov/roll-call-votes",
        }
        enriched += 1

    print("\n--- Voting data quality (House only) ---")
    print(f"  Representatives with vote data: {enriched}")
    print(f"  Roll calls analyzed:            {len(vote_refs)}")
    print(f"  Failed requests:                {fetcher.failures}")
    print("  (Senators intentionally blank: Senate votes not yet in the API)")

    return True


def _bill_label(v: Dict) -> Optional[str]:
    bt = v.get("legislationType") or v.get("billType")
    bn = v.get("legislationNumber") or v.get("billNumber")
    if bt and bn:
        return f"{str(bt).upper()} {bn}"
    return None


def _bill_url(v: Dict) -> Optional[str]:
    bt = v.get("legislationType") or v.get("billType")
    bn = v.get("legislationNumber") or v.get("billNumber")
    cong = v.get("congress")
    if bt and bn and cong:
        return (f"https://www.congress.gov/bill/{cong}th-congress/"
                f"{str(bt).lower()}/{bn}")
    return None
