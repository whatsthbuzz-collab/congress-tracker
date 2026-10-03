#!/usr/bin/env python3
"""
keyvotes.py. Key votes: how each member voted on the FINAL vote of every bill
that became law this Congress. Objective by construction: no editorial
picking. If a law passed a chamber by voice vote or unanimous consent, there
is no roll call and therefore no key vote for that chamber.

Sources (all official):
  Enacted laws   laws.LAST_LAWS (Congress.gov /law/{congress}/pub, already
                 fetched by add_laws, so no second download)
  Bill actions   Congress.gov /bill/{congress}/{type}/{number}/actions
                 -> actions[].recordedVotes[] {chamber, rollNumber, url, date}
                 where url is the chamber's own roll-call XML.
  House XML      clerk.house.gov, schema xml.house.gov/rollcall/vote.xsd:
                 vote-metadata/vote-question, legis-num, vote-result,
                 action-date; vote-data/recorded-vote/legislator@name-id
                 (Bioguide ID), @party; recorded-vote/vote.
  Senate XML     senate.gov LIS roll_call_votes (verified on
                 vote_119_2_00242.xml): question, vote_question_text,
                 vote_date, vote_result, members/member/lis_member_id,
                 vote_cast.

Which roll calls count as "final": House questions such as On Passage, On
Motion to Suspend the Rules and Pass, On Agreeing to the Conference Report,
and motions to concur in or agree to the Senate amendment; Senate questions
On Passage of the Bill, On the Joint Resolution, On the Conference Report, and
motions to concur. Cloture, motions to proceed, amendments, recommittals and
tabling are never key votes. If a chamber held more than one final vote on a
law (for example passage, then concurrence), the LATEST is used, since that is
the vote that sent the bill onward.

Output (kept compact; positions are per member, details stored once):
  payload["keyVotes"] = [{id, bill, title, chamber, date, question, result,
                          billUrl, voteUrl}]       newest first
  member["keyVotes"]  = {id: "Y"|"N"|"P"|"NV"}

Safety: a House vote whose legislator IDs mostly fail to match our roster is
skipped (the name-id format would have changed); nothing is guessed.
"""

import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

import laws as laws_mod

API_BASE = "https://api.congress.gov/v3"
API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()
REQUEST_DELAY = 0.3
MIN_ROSTER_MATCH = 0.8  # share of a vote's legislators that must match

HOUSE_FINAL = re.compile(
    r"^on (passage|motion to suspend the rules and pass|agreeing to the conference report"
    r"|motion to concur|motion that the house (agree|concur)|motion to agree to the senate amendment)",
    re.I)
SENATE_FINAL_Q = {"on passage of the bill", "on the joint resolution",
                  "on the conference report", "on the bill"}

TYPE_LABEL = {"HR": "H.R.", "S": "S.", "HJRES": "H.J.Res.", "SJRES": "S.J.Res.",
              "HRES": "H.Res.", "SRES": "S.Res.", "HCONRES": "H.Con.Res.",
              "SCONRES": "S.Con.Res."}
TYPE_SLUG = {"HR": "house-bill", "S": "senate-bill", "HJRES": "house-joint-resolution",
             "SJRES": "senate-joint-resolution"}


def _code(pos: str) -> Optional[str]:
    p = (pos or "").strip().lower()
    if p in ("yea", "aye", "yes"):
        return "Y"
    if p in ("nay", "no"):
        return "N"
    if p == "present":
        return "P"
    if p == "not voting":
        return "NV"
    return None


def is_final_house(question: str) -> bool:
    return bool(HOUSE_FINAL.match((question or "").strip()))


def is_final_senate(question: str, question_text: str) -> bool:
    q = (question or "").strip().lower()
    if q in SENATE_FINAL_Q:
        return True
    return q.startswith("on the motion") and "concur" in (question_text or "").lower()


class KeyVoteFetcher:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; congress-tracker/1.0)"})
        self.failures = 0

    def actions(self, congress: int, btype: str, number) -> List[Dict]:
        out, offset = [], 0
        while True:
            time.sleep(REQUEST_DELAY)
            try:
                r = self.s.get(f"{API_BASE}/bill/{congress}/{btype.lower()}/{number}/actions",
                               params={"api_key": self.api_key, "format": "json",
                                       "limit": 250, "offset": offset}, timeout=30)
                if r.status_code == 429:
                    time.sleep(30)
                    continue
                r.raise_for_status()
                batch = r.json().get("actions") or []
            except Exception as e:
                print(f"  [keyvotes] actions failed {btype}{number}: {e}", file=sys.stderr)
                self.failures += 1
                return out
            out.extend(batch)
            if len(batch) < 250:
                return out
            offset += 250

    def xml(self, url: str) -> Optional[ET.Element]:
        time.sleep(REQUEST_DELAY)
        try:
            r = self.s.get(url, timeout=(10, 30))
            r.raise_for_status()
            return ET.fromstring(r.content)
        except Exception as e:
            print(f"  [keyvotes] vote XML failed {url}: {e}", file=sys.stderr)
            self.failures += 1
            return None


def parse_house(root: ET.Element) -> Optional[Dict]:
    meta = root.find("vote-metadata")
    if meta is None:
        return None
    ad = meta.find("action-date")
    date = ""
    if ad is not None:
        raw = (ad.get("date") or "").strip()
        if re.fullmatch(r"\d{8}", raw):
            date = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        else:
            try:
                date = datetime.strptime((ad.text or "").strip(), "%d-%b-%Y").date().isoformat()
            except ValueError:
                date = ""
    votes = {}
    for rv in root.findall("vote-data/recorded-vote"):
        leg = rv.find("legislator")
        if leg is None:
            continue
        bid = (leg.get("name-id") or "").strip()
        code = _code(rv.findtext("vote") or "")
        if bid and code:
            votes[bid] = code
    return {"question": (meta.findtext("vote-question") or "").strip(),
            "result": (meta.findtext("vote-result") or "").strip(),
            "date": date, "votes": votes}


def parse_senate(root: ET.Element, lis_to_bid: Dict[str, str]) -> Optional[Dict]:
    raw = (root.findtext("vote_date") or "").strip()
    m = re.match(r"([A-Za-z]+ \d{1,2}, \d{4})", raw)
    date = ""
    if m:
        try:
            date = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    votes = {}
    for mem in root.findall("members/member"):
        bid = lis_to_bid.get((mem.findtext("lis_member_id") or "").strip())
        code = _code(mem.findtext("vote_cast") or "")
        if bid and code:
            votes[bid] = code
    return {"question": (root.findtext("question") or "").strip(),
            "questionText": (root.findtext("vote_question_text") or "").strip(),
            "result": (root.findtext("vote_result") or "").strip(),
            "date": date, "votes": votes}


def add_key_votes(members: List[Dict[str, Any]], congress: int) -> Optional[List[Dict]]:
    for m in members:
        m["keyVotes"] = {}
    laws = laws_mod.LAST_LAWS
    if not API_KEY or not laws:
        print("Key votes: skipped (no API key or no enacted-law list this run).")
        return None

    print(f"Fetching key votes on {len(laws)} enacted laws (Congress {congress})...")
    f = KeyVoteFetcher(API_KEY)
    by_bid = {m["bioguideId"]: m for m in members}
    house_ids = {m["bioguideId"] for m in members if m.get("chamber") != "Senate"}
    lis_to_bid = {m.get("lisId"): m["bioguideId"] for m in members if m.get("lisId")}

    key_votes: List[Dict] = []
    skipped_unmatched = 0
    for i, law in enumerate(laws, 1):
        btype = str(law.get("type") or law.get("billType") or "").upper()
        num = law.get("number") or law.get("billNumber")
        if not (btype and num):
            continue
        # Latest final roll call per chamber for this law.
        best: Dict[str, Dict] = {}
        seen = set()
        for act in f.actions(congress, btype, num):
            for rv in act.get("recordedVotes") or []:
                url = rv.get("url")
                chamber = rv.get("chamber")
                if not url or url in seen or chamber not in ("House", "Senate"):
                    continue
                seen.add(url)
                root = f.xml(url)
                if root is None:
                    continue
                if chamber == "House":
                    v = parse_house(root)
                    if not v or not is_final_house(v["question"]):
                        continue
                    ids = list(v["votes"])
                    if not ids or sum(1 for b in ids if b in house_ids) / len(ids) < MIN_ROSTER_MATCH:
                        skipped_unmatched += 1
                        continue
                else:
                    v = parse_senate(root, lis_to_bid)
                    if not v or not is_final_senate(v["question"], v.get("questionText", "")):
                        continue
                if not v["votes"] or not v["date"]:
                    continue
                v["voteUrl"] = url
                if chamber not in best or v["date"] >= best[chamber]["date"]:
                    best[chamber] = v
        label = f"{TYPE_LABEL.get(btype, btype)} {num}"
        slug = TYPE_SLUG.get(btype)
        bill_url = (f"https://www.congress.gov/bill/{congress}th-congress/{slug}/{num}"
                    if slug else None)
        for chamber, v in best.items():
            kid = f"{btype.lower()}{num}-{chamber[0].lower()}"
            key_votes.append({"id": kid, "bill": label, "title": law.get("title") or None,
                              "chamber": chamber, "date": v["date"], "question": v["question"],
                              "result": v["result"], "billUrl": bill_url,
                              "voteUrl": v["voteUrl"].replace(".xml", ".htm")
                              if chamber == "Senate" else v["voteUrl"]})
            for bid, code in v["votes"].items():
                if bid in by_bid:
                    by_bid[bid]["keyVotes"][kid] = code
        if i % 50 == 0:
            print(f"  {i}/{len(laws)} laws checked, {len(key_votes)} key votes so far")

    key_votes.sort(key=lambda k: k["date"], reverse=True)
    with_kv = sum(1 for m in members if m["keyVotes"])
    print("\n--- Key votes ---")
    print(f"  Key votes found:         {len(key_votes)} "
          f"(House {sum(k['chamber'] == 'House' for k in key_votes)}, "
          f"Senate {sum(k['chamber'] == 'Senate' for k in key_votes)})")
    print(f"  Members with key votes:  {with_kv}/{len(members)}")
    print(f"  House votes skipped (IDs did not match roster): {skipped_unmatched}")
    print(f"  Failed requests:         {f.failures}")
    return key_votes
