#!/usr/bin/env python3
"""
state_legislature.py. state legislators, votes, and bills via LegiScan.

Follows LegiScan's own guidance: use the weekly bulk datasets, and use the
hashes. Per state, per run:

  1. getDatasetList&state=XX       -> sessions with session_id, access_key,
                                      dataset_hash
  2. pick the current regular session (latest year_start, not special)
  3. if dataset_hash == the hash we stored last time -> SKIP (0 more calls)
  4. getDataset&id=..&access_key=.. -> base64 ZIP of every bill, vote, person
  5. parse locally, compute party-line / missed / sponsored, write JSON

Budget: at most 2 queries per state per week. The public key allows
30,000/month, so this is negligible even at 50 states.

Requires LEGISCAN_API_KEY. States come from STATES env (comma-separated
two-letter codes), default "TX".

Data is CC BY 4.0 from LegiScan; the UI credits them.
"""

import base64
import io
import json
import os
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import glob
import re
import tarfile

import requests
import yaml

API = "https://api.legiscan.com/"
KEY = os.environ.get("LEGISCAN_API_KEY", "").strip()
STATES = [s.strip().upper() for s in os.environ.get("STATES", "TX").split(",") if s.strip()]
OUT_DIR = os.path.join("public", "state")
INDEX = os.path.join(OUT_DIR, "index.json")

# OpenStates "people" repo: one YAML per legislator with official photo URL,
# email, and links. Public domain-ish (CC0 data). We match to LegiScan by
# state + chamber + district, which is exact wherever districts are single-member.
OPENSTATES_TGZ = "https://codeload.github.com/openstates/people/tar.gz/refs/heads/main"

# Term lengths (years) per chamber, from NCSL "Number of Legislators and Length
# of Terms in Years", and whether the senate is staggered (Ballotpedia).
# senate_mode: "two" = 2-year (all up every even year), "all" = 4-year with all
# seats up together (ref = a known election year), "stagger" = 4-year staggered
# (per-member class unknown -> no year shown). House: 2-year everywhere except
# AL/LA/MD/MS (4-year, all together) and ND (4-year, staggered).
TERMS = {
    "AL": (4, "all", 2026, 4, "all", 2026), "AK": (4, "stagger", None, 2, "even", None),
    "AZ": (2, "two", None, 2, "even", None), "AR": (4, "stagger", None, 2, "even", None),
    "CA": (4, "stagger", None, 2, "even", None), "CO": (4, "stagger", None, 2, "even", None),
    "CT": (2, "two", None, 2, "even", None), "DE": (4, "stagger", None, 2, "even", None),
    "FL": (4, "stagger", None, 2, "even", None), "GA": (2, "two", None, 2, "even", None),
    "HI": (4, "stagger", None, 2, "even", None), "ID": (2, "two", None, 2, "even", None),
    "IL": (4, "stagger", None, 2, "even", None), "IN": (4, "stagger", None, 2, "even", None),
    "IA": (4, "stagger", None, 2, "even", None), "KS": (4, "all", 2028, 2, "even", None),
    "KY": (4, "stagger", None, 2, "even", None), "LA": (4, "all", 2027, 4, "all", 2027),
    "ME": (2, "two", None, 2, "even", None), "MD": (4, "all", 2026, 4, "all", 2026),
    "MA": (2, "two", None, 2, "even", None), "MI": (4, "all", 2026, 2, "even", None),
    "MN": (4, "all", 2026, 2, "even", None), "MS": (4, "all", 2027, 4, "all", 2027),
    "MO": (4, "stagger", None, 2, "even", None), "MT": (4, "stagger", None, 2, "even", None),
    "NE": (4, "stagger", None, None, None, None), "NV": (4, "stagger", None, 2, "even", None),
    "NH": (2, "two", None, 2, "even", None), "NJ": (4, "stagger", None, 2, "odd", None),
    "NM": (4, "all", 2028, 2, "even", None), "NY": (2, "two", None, 2, "even", None),
    "NC": (2, "two", None, 2, "even", None), "ND": (4, "stagger", None, 4, "stagger", None),
    "OH": (4, "stagger", None, 2, "even", None), "OK": (4, "stagger", None, 2, "even", None),
    "OR": (4, "stagger", None, 2, "even", None), "PA": (4, "stagger", None, 2, "even", None),
    "RI": (2, "two", None, 2, "even", None), "SC": (4, "all", 2028, 2, "even", None),
    "SD": (2, "two", None, 2, "even", None), "TN": (4, "stagger", None, 2, "even", None),
    "TX": (4, "stagger", None, 2, "even", None), "UT": (4, "stagger", None, 2, "even", None),
    "VT": (2, "two", None, 2, "even", None), "VA": (4, "all", 2027, 2, "odd", None),
    "WA": (4, "stagger", None, 2, "even", None), "WV": (4, "stagger", None, 2, "even", None),
    "WI": (4, "stagger", None, 2, "even", None), "WY": (4, "stagger", None, 2, "even", None),
}


def term_info(code: str, chamber: str) -> Dict[str, Any]:
    """Term length + next election year where it is knowable."""
    row = TERMS.get(code)
    if not row:
        return {"termYears": None, "nextElection": None, "electionNote": "Term length not on file"}
    sy, smode, sref, hy, hmode, href = row
    years, mode, ref = (sy, smode, sref) if chamber == "Senate" else (hy, hmode, href)
    now = datetime.now(timezone.utc).year
    if years is None:
        return {"termYears": None, "nextElection": None, "electionNote": "Unicameral"}
    if mode == "two" or mode == "even":
        nxt = now if now % 2 == 0 else now + 1
        return {"termYears": years, "nextElection": nxt, "electionNote": None}
    if mode == "odd":
        nxt = now if now % 2 == 1 else now + 1
        return {"termYears": years, "nextElection": nxt, "electionNote": None}
    if mode == "all" and ref:
        nxt = ref
        while nxt < now:
            nxt += years
        return {"termYears": years, "nextElection": nxt, "electionNote": "All seats elected together"}
    return {"termYears": years, "nextElection": None,
            "electionNote": f"{years}-year terms, staggered. See Ballotpedia for this seat"}


def fetch_openstates(states: List[str]) -> Dict[str, Dict[tuple, Dict[str, Any]]]:
    """
    Download the OpenStates people repo once and index the requested states:
      {code: {(chamber, district): {image, email, ballotpedia, links, lastName}}}
    """
    out: Dict[str, Dict[tuple, Dict[str, Any]]] = {c: {} for c in states}
    try:
        r = requests.get(OPENSTATES_TGZ, timeout=(10, 180))
        r.raise_for_status()
    except Exception as e:
        print(f"  [openstates] download failed: {e}", file=sys.stderr)
        return out
    print(f"  OpenStates archive: {len(r.content) / 1048576:.1f} MB")
    try:
        tf = tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz")
    except Exception as e:
        print(f"  [openstates] bad archive: {e}", file=sys.stderr)
        return out
    wanted = {c.lower() for c in states}
    committees: Dict[str, List[Dict[str, Any]]] = {c: [] for c in states}
    for member in tf.getmembers():
        cm = re.match(r"[^/]+/data/([a-z]{2})/committees/[^/]+\.yml$", member.name)
        if cm and cm.group(1) in wanted:
            try:
                d = yaml.safe_load(tf.extractfile(member).read()) or {}
            except Exception:
                continue
            committees[cm.group(1).upper()].append({
                "name": d.get("name"),
                "chamber": {"upper": "Senate", "lower": "House"}.get(d.get("chamber"), "Joint"),
                "kind": d.get("classification") or "committee",
                "parent": d.get("parent"),
                "url": next((l.get("url") for l in (d.get("links") or []) if l.get("url")), None),
                "members": [{"personId": x.get("person_id"), "role": (x.get("role") or "member")}
                            for x in (d.get("members") or []) if x.get("person_id")],
            })
            continue
        m = re.match(r"[^/]+/data/([a-z]{2})/legislature/[^/]+\.yml$", member.name)
        if not m or m.group(1) not in wanted:
            continue
        try:
            d = yaml.safe_load(tf.extractfile(member).read()) or {}
        except Exception:
            continue
        roles = [x for x in (d.get("roles") or []) if x.get("type") in ("lower", "upper") and not x.get("end_date")]
        if not roles:
            continue
        role = roles[-1]
        chamber = "House" if role["type"] == "lower" else "Senate"
        district = str(role.get("district") or "").lstrip("0")
        code = m.group(1).upper()
        bp = next((s.get("url") for s in (d.get("sources") or []) if "ballotpedia.org" in (s.get("url") or "")), None)
        rec = {
            "osId": d.get("id"),
            "image": d.get("image"), "email": d.get("email"), "ballotpedia": bp,
            "links": [l.get("url") for l in (d.get("links") or []) if l.get("url")][:3],
            "lastName": (d.get("family_name") or "").lower(),
            "name": d.get("name"),
        }
        key = (chamber, district)
        # Multi-member districts: keep a list, resolve by last name later.
        out[code].setdefault(key, []).append(rec)
    for c in states:
        print(f"  OpenStates {c}: {sum(len(v) for v in out[c].values())} legislators with profiles, "
              f"{len(committees[c])} committees")
    # Stash committees on the index under a reserved key.
    for c in states:
        out[c][("__committees__", "")] = committees[c]
    return out


def openstates_match(idx: Dict[tuple, List[Dict]], chamber: str, district: Optional[str],
                     last_name: str) -> Optional[Dict[str, Any]]:
    cands = idx.get((chamber, str(district or "").lstrip("0"))) or []
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    ln = (last_name or "").lower()
    for c in cands:
        if c["lastName"] and (c["lastName"] in ln or ln in c["lastName"]):
            return c
    return None

RECENT_PER_MEMBER = 10
SPONSOR_PRIMARY = 1
SCHEMA_VERSION = 4  # bump when the parser/output changes; forces a refresh  # sponsor_type_id 1 = primary sponsor in LegiScan

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
PARTY_FULL = {"D": "Democratic", "R": "Republican", "I": "Independent", "L": "Libertarian",
              "G": "Green", "N": "Nonpartisan", "P": "Progressive", "": "Nonpartisan"}


class LegiScan:
    def __init__(self, key: str):
        self.key = key
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.calls = 0

    def op(self, operation: str, **params) -> Optional[Dict[str, Any]]:
        p = {"key": self.key, "op": operation, **params}
        for attempt in range(3):
            self.calls += 1
            try:
                r = self.s.get(API, params=p, timeout=(10, 180))
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f"  [legiscan] {operation} attempt {attempt + 1} failed: {e}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
                continue
            if data.get("status") == "OK":
                return data
            # LegiScan puts the reason in "alert"; print it so the log explains itself.
            print(f"  [legiscan] {operation} status={data.get('status')} "
                  f"alert={json.dumps(data.get('alert'))[:300]}", file=sys.stderr)
            if str(data.get("status")).upper() == "ERROR":
                return None  # a real error (bad key, bad state) won't fix itself
            time.sleep(5 * (attempt + 1))
        return None


def pick_session(datasets: List[Dict]) -> Optional[Dict]:
    """Most recent regular session; fall back to most recent of any kind."""
    if not datasets:
        return None
    regular = [d for d in datasets if not d.get("special")]
    pool = regular or datasets
    return max(pool, key=lambda d: (d.get("year_start") or 0, d.get("session_id") or 0))


def load_previous_index() -> Dict[str, Any]:
    try:
        with open(INDEX) as f:
            return json.load(f)
    except Exception:
        return {"states": []}


def parse_zip(blob: bytes) -> Dict[str, List[Dict]]:
    """Split the dataset ZIP into people / bills / roll calls."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    out = {"people": [], "bills": [], "votes": []}
    for name in z.namelist():
        if not name.lower().endswith(".json"):
            continue
        low = name.lower()
        try:
            obj = json.loads(z.read(name))
        except Exception:
            continue
        if "/people/" in low and "person" in obj:
            out["people"].append(obj["person"])
        elif "/bill/" in low and "bill" in obj:
            out["bills"].append(obj["bill"])
        elif "/vote/" in low and "roll_call" in obj:
            out["votes"].append(obj["roll_call"])
    return out


def _district(raw: str) -> Optional[str]:
    """'HD-014' -> '14'; 'SD-3' -> '3'; anything else returned as-is."""
    if not raw:
        return None
    part = raw.split("-", 1)[-1]
    return part.lstrip("0") or part


def _majority(records: List[Dict], party: str) -> Optional[str]:
    c = Counter(r["pos"] for r in records if r["party"] == party and r["pos"] in ("Yea", "Nay"))
    y, n = c.get("Yea", 0), c.get("Nay", 0)
    if y == n:
        return None
    return "Yea" if y > n else "Nay"


def build_state(code: str, session: Dict, data: Dict[str, List[Dict]],
                os_idx: Dict[tuple, List[Dict]]) -> Dict[str, Any]:
    people = data["people"]; bills = data["bills"]; votes = data["votes"]
    print(f"  {code}: {len(people)} people, {len(bills)} bills, {len(votes)} roll calls")

    if people:
        print("  [debug] person keys:", sorted(people[0].keys())[:25])
    if votes:
        v0 = votes[0]
        print("  [debug] roll_call keys:", sorted(v0.keys()))
        if v0.get("votes"):
            print("  [debug] vote record:", v0["votes"][0])
    if bills:
        b0 = bills[0]
        print("  [debug] bill keys:", sorted(b0.keys())[:30])
        if b0.get("sponsors"):
            print("  [debug] sponsor record:", {k: b0['sponsors'][0].get(k) for k in
                  ('people_id', 'sponsor_type_id', 'sponsor_order', 'name')})

    # ---- legislators ----
    legs: Dict[int, Dict[str, Any]] = {}
    skipped_committees = 0
    for p in people:
        pid = p.get("people_id")
        if not pid:
            continue
        # LegiScan records committees as "people" so they can appear as bill
        # sponsors (California's Committee on Budget authors dozens of bills).
        # They have no party, district, or votes. Exclude them.
        if p.get("committee_sponsor") or p.get("committee_id") or \
                not (p.get("last_name") or "").strip() or \
                (p.get("name") or "").lower().startswith("committee"):
            skipped_committees += 1
            continue
        role = (p.get("role") or "").strip()
        chamber = "Senate" if role.lower().startswith("sen") else "House"
        party_code = (p.get("party") or "").strip().upper()[:1]
        legs[pid] = {
            "id": f"{code}-{pid}",
            "peopleId": pid,
            "name": p.get("name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "firstName": p.get("first_name"), "lastName": p.get("last_name"),
            "party": PARTY_FULL.get(party_code, p.get("party") or "Unknown"),
            "partyCode": party_code,
            "chamber": chamber,
            "role": role,
            "district": _district(p.get("district")),
            "districtRaw": p.get("district"),
            "state": STATE_NAMES.get(code, code), "stateCode": code,
            "ballotpedia": (f"https://ballotpedia.org/{p['ballotpedia']}"
                            if p.get("ballotpedia") else None),
            "votesmartId": p.get("votesmart_id"),
            "photo": None, "email": None, "links": [],
            **term_info(code, chamber),
            "bills": [], "billsTotal": 0, "billsPrimary": 0,
            "voting": None,
            "source": "LegiScan",
            "sourceUrl": f"https://legiscan.com/{code}/people/{pid}",
        }

    # ---- OpenStates enrichment: photo, email, links ----
    matched = 0
    for leg in legs.values():
        rec = openstates_match(os_idx, leg["chamber"], leg["district"], leg["lastName"] or "")
        if rec:
            leg["osId"] = rec.get("osId")
            leg["photo"] = rec.get("image") or None
            leg["email"] = rec.get("email") or None
            leg["links"] = rec.get("links") or []
            if not leg["ballotpedia"] and rec.get("ballotpedia"):
                leg["ballotpedia"] = rec["ballotpedia"]
            matched += 1
    print(f"  {code}: {matched}/{len(legs)} matched to OpenStates profiles (photos); "
          f"{skipped_committees} committee records excluded")

    # ---- committees (OpenStates rosters, joined on the person id) ----
    LEAD = {"chair", "co-chair", "vice chair", "vice-chair", "ranking member", "chairman", "chairwoman"}
    by_os_id = {leg["osId"]: leg for leg in legs.values() if leg.get("osId")}
    comm_list = os_idx.get(("__committees__", "")) or []
    for leg in legs.values():
        leg["committees"] = []
    for c in comm_list:
        for mem in c["members"]:
            leg = by_os_id.get(mem["personId"])
            if not leg:
                continue
            role = (mem["role"] or "member").strip().lower()
            leg["committees"].append({
                "name": c["name"], "chamber": c["chamber"], "kind": c["kind"],
                "role": role.title() if role in LEAD else "Member", "url": c["url"],
            })
    for leg in legs.values():
        leg["committees"].sort(key=lambda x: (0 if x["role"] != "Member" else 1, x["name"] or ""))
    with_comms = sum(1 for leg in legs.values() if leg["committees"])
    print(f"  {code}: {with_comms}/{len(legs)} legislators with committee assignments")

    # ---- campaign finance: a link, not a number. State disclosure systems differ
    # in all 50 states; FollowTheMoney (now part of OpenSecrets) is the one place
    # that unifies them, and LegiScan carries each legislator's id there.
    for p in people:
        pid = p.get("people_id")
        leg = legs.get(pid)
        if not leg:
            continue
        eid = p.get("followthemoney_eid")
        leg["financeUrl"] = (f"https://www.followthemoney.org/entity-details?eid={eid}"
                             if eid else None)

    # ---- departed members: LegiScan's session roster keeps everyone who served
    # at any point (a member who resigned in March AND their replacement). When
    # two people share one single-member seat, OpenStates (which tracks who is
    # currently seated) tells us which one is current; the other is marked
    # former. Skipped for states with multi-member districts, where a shared
    # district is normal.
    multi_member = any(len(v) > 1 for k, v in os_idx.items() if k[0] != "__committees__")
    former = 0
    if not multi_member:
        by_seat: Dict[tuple, List[Dict]] = defaultdict(list)
        for leg in legs.values():
            if leg["district"]:
                by_seat[(leg["chamber"], str(leg["district"]))].append(leg)
        for seat, group in by_seat.items():
            if len(group) < 2:
                continue
            current = os_idx.get(seat) or []
            cur_last = {c["lastName"] for c in current if c.get("lastName")}
            if not cur_last:
                continue  # OpenStates has nobody here; leave everyone as-is
            keep = [g for g in group if (g["lastName"] or "").lower() in cur_last]
            if len(keep) == 1:
                for g in group:
                    if g is not keep[0]:
                        g["former"] = True
                        former += 1
    for leg in legs.values():
        leg.setdefault("former", False)
    print(f"  {code}: {former} members who left during the session set aside"
          + (" (multi-member districts; skipped)" if multi_member else ""))

    # ---- bills by id, sponsorship ----
    bill_by_id = {b.get("bill_id"): b for b in bills if b.get("bill_id")}
    sponsored: Dict[int, List[Dict]] = defaultdict(list)
    for b in bills:
        for sp in b.get("sponsors") or []:
            pid = sp.get("people_id")
            if pid in legs:
                sponsored[pid].append({
                    "billNumber": b.get("bill_number"),
                    "title": b.get("title") or "",
                    "status": b.get("status_date"),
                    "lastAction": ((b.get("history") or [{}])[-1].get("action") if b.get("history") else "") or "",
                    "primary": sp.get("sponsor_type_id") == SPONSOR_PRIMARY or sp.get("sponsor_order") == 1,
                    "url": b.get("url"),
                    "stateUrl": b.get("state_link"),
                    "date": (b.get("status_date") or ""),
                })
    for pid, lst in sponsored.items():
        lst.sort(key=lambda x: x["date"] or "", reverse=True)
        legs[pid]["billsTotal"] = len(lst)
        legs[pid]["billsPrimary"] = sum(1 for x in lst if x["primary"])
        legs[pid]["bills"] = lst[:RECENT_PER_MEMBER]

    # ---- roll calls -> party-line / missed ----
    tally = {pid: {"with": 0, "against": 0, "missed": 0, "eligible": 0, "recent": []} for pid in legs}
    votes_sorted = sorted(votes, key=lambda v: v.get("date") or "", reverse=True)
    analyzed = 0
    for v in votes_sorted:
        recs = []
        for rv in v.get("votes") or []:
            pid = rv.get("people_id")
            if pid not in legs:
                continue
            txt = (rv.get("vote_text") or "").strip()
            pos = "Yea" if txt.lower() in ("yea", "yes", "aye") else \
                  "Nay" if txt.lower() in ("nay", "no") else \
                  "Not Voting" if txt.upper() in ("NV", "ABSENT", "EXCUSED") else txt
            recs.append({"pid": pid, "pos": pos, "party": legs[pid]["partyCode"]})
        if not recs:
            continue
        analyzed += 1
        maj = {"D": _majority(recs, "D"), "R": _majority(recs, "R")}
        b = bill_by_id.get(v.get("bill_id")) or {}
        meta = {
            "date": (v.get("date") or "")[:10],
            "question": v.get("desc") or "",
            "result": "Passed" if v.get("passed") else "Failed",
            "chamber": "Senate" if str(v.get("chamber", "")).upper().startswith("S") else "House",
            "bill": b.get("bill_number"),
            "billTitle": (b.get("title") or "")[:120],
            "billUrl": b.get("url"),
        }
        for r in recs:
            t = tally[r["pid"]]
            t["eligible"] += 1
            if r["pos"] == "Not Voting":
                t["missed"] += 1
            elif r["pos"] in ("Yea", "Nay"):
                pl = maj.get(r["party"])
                if pl is not None:
                    if r["pos"] == pl:
                        t["with"] += 1
                    else:
                        t["against"] += 1
            if len(t["recent"]) < RECENT_PER_MEMBER:
                t["recent"].append({**meta, "position": r["pos"]})

    with_votes = 0
    for pid, leg in legs.items():
        t = tally[pid]
        if t["eligible"] == 0:
            continue
        partisan = t["with"] + t["against"]
        leg["voting"] = {
            "partyLinePct": round(t["with"] / partisan * 100) if partisan else None,
            "missedPct": round(t["missed"] / t["eligible"] * 100),
            "votesTotal": t["eligible"],
            "votesWithParty": t["with"], "votesAgainstParty": t["against"],
            "recentVotes": t["recent"],
        }
        with_votes += 1

    legislators = sorted((l for l in legs.values() if not l.get("former")),
                         key=lambda l: (l["chamber"], l["lastName"] or l["name"]))
    print(f"  {code}: {len(legislators)} legislators, {with_votes} with vote data, "
          f"{analyzed} roll calls analyzed")

    return {
        "code": code,
        "name": STATE_NAMES.get(code, code),
        "session": {
            "id": session.get("session_id"),
            "name": session.get("session_name") or session.get("name"),
            "yearStart": session.get("year_start"), "yearEnd": session.get("year_end"),
        },
        "datasetHash": session.get("dataset_hash"),
        "datasetDate": session.get("dataset_date"),
        "counts": {"legislators": len(legislators), "bills": len(bills), "rollCalls": len(votes),
                   "former": former, "multiMemberDistricts": multi_member},
        "legislators": legislators,
        "source": "LegiScan (CC BY 4.0)",
        "sourceUrl": f"https://legiscan.com/{code}",
    }


def main():
    if not KEY:
        print("ERROR: LEGISCAN_API_KEY not set. Add it as a repo secret.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    prev_index = {e["code"]: e for e in load_previous_index().get("states", [])}
    api = LegiScan(KEY)
    index_entries: List[Dict[str, Any]] = []
    changed = 0

    # Decide which states actually need a refresh first (hash check), so we
    # only download OpenStates if at least one state changed.
    plan = []
    for code in STATES:
        print(f"\n=== {code} ({STATE_NAMES.get(code, code)}) ===")
        lst = api.op("getDatasetList", state=code)
        datasets = (lst or {}).get("datasetlist") or []
        session = pick_session(datasets)
        if not session:
            print(f"  {code}: no datasets available; keeping previous file if any")
            if code in prev_index:
                index_entries.append(prev_index[code])
            continue
        print(f"  Session: {session.get('session_name')} (id {session.get('session_id')}, "
              f"hash {str(session.get('dataset_hash'))[:10]}…, date {session.get('dataset_date')})")
        old = prev_index.get(code) or {}
        if old.get("datasetHash") == session.get("dataset_hash") and \
                old.get("schemaVersion") == SCHEMA_VERSION and \
                os.path.exists(os.path.join(OUT_DIR, f"{code}.json")):
            print(f"  {code}: dataset unchanged -- skipping (hash match)")
            index_entries.append(old)
            continue
        if old.get("datasetHash") == session.get("dataset_hash"):
            print(f"  {code}: parser updated (schema v{SCHEMA_VERSION}); rebuilding from a fresh download")
        plan.append((code, session))

    os_idx = fetch_openstates([c for c, _ in plan]) if plan else {}

    for code, session in plan:
        ds = api.op("getDataset", id=session["session_id"], access_key=session["access_key"])
        if not ds or not (ds.get("dataset") or {}).get("zip"):
            print(f"  {code}: dataset download failed; keeping previous file if any")
            if code in prev_index:
                index_entries.append(prev_index[code])
            continue
        blob = base64.b64decode(ds["dataset"]["zip"])
        print(f"  {code}: downloaded {len(blob) / 1048576:.1f} MB")
        state = build_state(code, session, parse_zip(blob), os_idx.get(code, {}))
        with open(os.path.join(OUT_DIR, f"{code}.json"), "w") as f:
            json.dump(state, f)
        index_entries.append({
            "code": code, "name": state["name"], "session": state["session"],
            "datasetHash": state["datasetHash"], "datasetDate": state["datasetDate"],
            "counts": state["counts"], "schemaVersion": SCHEMA_VERSION,
        })
        changed += 1
        del blob  # free the ZIP before the next state; some are hundreds of MB
        time.sleep(2)

    index_entries.sort(key=lambda e: e["name"])
    with open(INDEX, "w") as f:
        json.dump({"lastUpdated": datetime.now(timezone.utc).isoformat(),
                   "states": index_entries}, f, indent=1)
    total_mb = sum(os.path.getsize(os.path.join(OUT_DIR, fn)) for fn in os.listdir(OUT_DIR)) / 1048576
    print(f"\nWrote {INDEX} + {len(index_entries)} state file(s) ({total_mb:.1f} MB total); "
          f"{changed} refreshed; API calls this run: {api.calls}")


if __name__ == "__main__":
    main()
