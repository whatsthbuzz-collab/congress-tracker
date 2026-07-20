#!/usr/bin/env python3
"""
votes.py — add federal roll-call voting behavior to each member.

Source: GovTrack's public-domain mirror of the unitedstates/congress vote
data (https://www.govtrack.us/data/congress/{congress}/votes/{session}/).
No API key. Each roll-call vote is a data.json with this shape:

    {
      "chamber": "s", "congress": 119, "number": 81,
      "date": "...", "vote_id": "s81-119.2026",
      "category": "passage", "result": "Agreed to",
      "question": "...", "requires": "1/2",
      "bill": {"type": "s", "number": 4796, "congress": 119},
      "votes": {
        "Yea": [{"id":"S000148","party":"D","state":"NY"}, ...],
        "Nay": [...], "Present": [...], "Not Voting": [...]
      }
    }

Positions are keyed by Bioguide ID -- the same ID our roster uses -- so the
join is exact, no name matching.

What this computes per member:
  - partyLinePct    % of party-split votes where they sided with their party
  - missedPct       % of eligible votes they missed ("Not Voting")
  - votesTotal      how many roll calls we evaluated them on
  - recentVotes     up to N most recent votes with their individual position

"Party-line" is defined honestly: for each vote we find the majority position
of each major party. A member is "with party" when their Yea/Nay matches the
majority of their own party on that vote. Votes where a member's party has no
clear majority position, and votes the member missed, are excluded from the
denominator -- so the percentage reflects real partisan choices, not absences.
"""

import os
import sys
import json
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import requests

GOVTRACK_BASE = "https://www.govtrack.us/data/congress"

# How many of the most recent roll-call votes to analyze. The current Congress
# can have 500-900 votes; we take the most recent CAP for a current, useful
# picture without downloading everything (one HTTP call per vote).
VOTE_CAP = 200

# How many individual votes to surface per member in the UI.
RECENT_PER_MEMBER = 10

REQUEST_DELAY = 0.15  # GovTrack is a static file host; be polite anyway.

# Map our roster's party names to the single letters GovTrack uses.
PARTY_LETTER = {"Democratic": "D", "Republican": "R", "Independent": "I"}


class VoteFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.failures = 0
        self._dumped = False

    def _get_json(self, url: str) -> Optional[Any]:
        time.sleep(REQUEST_DELAY)
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            print(f"  [votes] request failed ({url}): {e}", file=sys.stderr)
            self.failures += 1
            return None

    def find_latest_vote_number(self, congress: int, session: str,
                                chamber: str) -> int:
        """
        Highest vote number for ONE chamber in a session, via exponential +
        binary search on data.json existence. No directory listing needed.
        """
        def exists(n: int) -> bool:
            url = f"{GOVTRACK_BASE}/{congress}/votes/{session}/{chamber}{n}/data.json"
            return self._get_json(url) is not None

        low, high = 0, 1
        while exists(high):
            low = high
            high *= 2
            if high > 5000:
                break
        while high - low > 1:
            mid = (low + high) // 2
            if exists(mid):
                low = mid
            else:
                high = mid
        return low

    def fetch_session_votes(self, congress: int, session: str,
                            cap_per_chamber: int) -> List[Dict]:
        """Fetch up to `cap_per_chamber` recent votes from each chamber."""
        votes = []
        for chamber in ("h", "s"):
            top = self.find_latest_vote_number(congress, session, chamber)
            if top == 0:
                continue
            label = "House" if chamber == "h" else "Senate"
            recent = min(cap_per_chamber, top)
            print(f"  Session {session} {label}: latest #{top}, "
                  f"pulling most recent {recent}")
            start = max(1, top - cap_per_chamber + 1)
            for n in range(start, top + 1):
                v = self.fetch_vote(congress, session, f"{chamber}{n}")
                if v:
                    votes.append(v)
        return votes

    def fetch_vote(self, congress: int, session: str, vote_dir: str) -> Optional[Dict]:
        url = f"{GOVTRACK_BASE}/{congress}/votes/{session}/{vote_dir}/data.json"
        data = self._get_json(url)
        if not data:
            return None

        if not self._dumped:
            self._dumped = True
            keys = list(data.keys())
            print("\n  [debug] raw vote data.json keys:", keys)
            vb = data.get("votes") or {}
            print("  [debug] vote option buckets:", list(vb.keys()))
            # Show one voter record shape.
            for opt, voters in vb.items():
                if isinstance(voters, list) and voters:
                    print(f"  [debug] sample voter in '{opt}':",
                          json.dumps(voters[0])[:200])
                    break
            print()

        return data


def _majority_position(voters: List[Dict], party_letter: str) -> Optional[str]:
    """
    Given the Yea and Nay voter lists for one party, return whichever the
    party did more of ('Yea' or 'Nay'), or None if no clear majority.
    `voters` here is a list of (position, party) already filtered.
    """
    counts = Counter(pos for pos, party in voters if party == party_letter)
    yea, nay = counts.get("Yea", 0), counts.get("Nay", 0)
    if yea == 0 and nay == 0:
        return None
    if yea == nay:
        return None
    return "Yea" if yea > nay else "Nay"


def add_votes(members: List[Dict[str, Any]], congress: int) -> bool:
    """
    Enrich members with voting behavior. Mutates members in place.
    Returns True (votes are always attempted; no key required).
    """
    print(f"Fetching federal roll-call votes (Congress {congress})...")
    fetcher = VoteFetcher()

    # Current Congress spans two sessions (odd year = 1, even = 2). Pull recent
    # votes from each chamber in each session.
    all_votes: List[Dict] = []
    for session in ("1", "2"):
        session_votes = fetcher.fetch_session_votes(congress, session, VOTE_CAP)
        all_votes.extend(session_votes)

    if not all_votes:
        print("  No votes retrieved. Leaving vote fields empty.")
        print(f"  Failed requests: {fetcher.failures}")
        for m in members:
            m["voting"] = None
        return False

    # Sort all collected votes newest-first by date for the "recent" list.
    all_votes.sort(key=lambda v: v.get("date") or "", reverse=True)
    print(f"  Analyzing {len(all_votes)} roll-call votes.")

    # Build a fast lookup: bioguide -> member row.
    by_bioguide = {m["bioguideId"]: m for m in members}

    # Per-member tallies.
    tally = {
        bid: {"with": 0, "against": 0, "missed": 0, "eligible": 0, "recent": []}
        for bid in by_bioguide
    }

    for v in all_votes:
        buckets = v.get("votes") or {}

        # Flatten to (bioguide, position, party) once per vote.
        records = []
        for position, voters in buckets.items():
            if not isinstance(voters, list):
                continue
            for voter in voters:
                if not isinstance(voter, dict):
                    continue
                bid = voter.get("id")
                if bid:
                    records.append((bid, position, voter.get("party")))

        # Determine each major party's majority position on this vote.
        yn = [(pos, party) for bid, pos, party in records if pos in ("Yea", "Nay")]
        dem_majority = _majority_position(yn, "D")
        rep_majority = _majority_position(yn, "R")
        majority_by_party = {"D": dem_majority, "R": rep_majority}

        # Which members were eligible (i.e. appear in this vote at all)?
        vote_meta = {
            "voteId": v.get("vote_id"),
            "date": (v.get("date") or "")[:10],
            "question": v.get("question") or v.get("category") or "",
            "result": v.get("result") or "",
            "chamber": "Senate" if v.get("chamber") == "s" else "House",
        }
        bill = v.get("bill") or {}
        if bill.get("type") and bill.get("number") and bill.get("congress"):
            vote_meta["bill"] = f"{bill['type'].upper()} {bill['number']}"
            vote_meta["billUrl"] = (
                f"https://www.congress.gov/bill/{bill['congress']}th-congress/"
                f"{bill['type']}/{bill['number']}"
            )

        for bid, position, party in records:
            t = tally.get(bid)
            if t is None:
                continue  # not a current member (e.g. former member mid-term)

            t["eligible"] += 1

            if position == "Not Voting":
                t["missed"] += 1
            elif position in ("Yea", "Nay"):
                pl = majority_by_party.get(party)
                if pl is not None:
                    if position == pl:
                        t["with"] += 1
                    else:
                        t["against"] += 1

            # Record the member's individual position for the recent list.
            if len(t["recent"]) < RECENT_PER_MEMBER:
                t["recent"].append({**vote_meta, "position": position})

    # Fold tallies into member rows.
    enriched = 0
    for bid, m in by_bioguide.items():
        t = tally[bid]
        eligible = t["eligible"]
        if eligible == 0:
            m["voting"] = None
            continue

        partisan = t["with"] + t["against"]
        party_line_pct = round(t["with"] / partisan * 100) if partisan else None
        missed_pct = round(t["missed"] / eligible * 100) if eligible else None

        m["voting"] = {
            "partyLinePct": party_line_pct,
            "missedPct": missed_pct,
            "votesTotal": eligible,
            "votesWithParty": t["with"],
            "votesAgainstParty": t["against"],
            "recentVotes": t["recent"],
            "source": "GovTrack / unitedstates congress project",
            "sourceUrl": "https://www.govtrack.us/congress/votes",
        }
        enriched += 1

    print("\n--- Voting data quality ---")
    print(f"  Members with vote data: {enriched}/{len(members)}")
    print(f"  Roll calls analyzed:    {len(all_votes)}")
    print(f"  Failed requests:        {fetcher.failures}")

    return True
