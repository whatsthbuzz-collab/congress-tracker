#!/usr/bin/env python3
"""
state_legislature.py — state legislators, votes, and bills via LegiScan.

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

import requests

API = "https://api.legiscan.com/"
KEY = os.environ.get("LEGISCAN_API_KEY", "").strip()
STATES = [s.strip().upper() for s in os.environ.get("STATES", "TX").split(",") if s.strip()]
OUT = os.path.join("public", "state_data.json")

RECENT_PER_MEMBER = 10
SPONSOR_PRIMARY = 1  # sponsor_type_id 1 = primary sponsor in LegiScan

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
              "G": "Green", "N": "Nonpartisan"}


class LegiScan:
    def __init__(self, key: str):
        self.key = key
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.calls = 0

    def op(self, operation: str, **params) -> Optional[Dict[str, Any]]:
        p = {"key": self.key, "op": operation, **params}
        self.calls += 1
        try:
            r = self.s.get(API, params=p, timeout=(10, 120))
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [legiscan] {operation} failed: {e}", file=sys.stderr)
            return None
        if data.get("status") != "OK":
            print(f"  [legiscan] {operation} returned status {data.get('status')}: "
                  f"{str(data.get('alert', ''))[:200]}", file=sys.stderr)
            return None
        return data


def pick_session(datasets: List[Dict]) -> Optional[Dict]:
    """Most recent regular session; fall back to most recent of any kind."""
    if not datasets:
        return None
    regular = [d for d in datasets if not d.get("special")]
    pool = regular or datasets
    return max(pool, key=lambda d: (d.get("year_start") or 0, d.get("session_id") or 0))


def load_previous() -> Dict[str, Any]:
    try:
        with open(OUT) as f:
            return json.load(f)
    except Exception:
        return {"states": {}}


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


def build_state(code: str, session: Dict, data: Dict[str, List[Dict]]) -> Dict[str, Any]:
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
    for p in people:
        pid = p.get("people_id")
        if not pid:
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
            "bills": [], "billsTotal": 0, "billsPrimary": 0,
            "voting": None,
            "source": "LegiScan",
            "sourceUrl": f"https://legiscan.com/{code}/people/{pid}",
        }

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

    legislators = sorted(legs.values(), key=lambda l: (l["chamber"], l["lastName"] or l["name"]))
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
        "counts": {"legislators": len(legislators), "bills": len(bills), "rollCalls": len(votes)},
        "legislators": legislators,
        "source": "LegiScan (CC BY 4.0)",
        "sourceUrl": f"https://legiscan.com/{code}",
    }


def main():
    if not KEY:
        print("ERROR: LEGISCAN_API_KEY not set. Add it as a repo secret.", file=sys.stderr)
        sys.exit(1)

    prev = load_previous()
    out = {"lastUpdated": datetime.now(timezone.utc).isoformat(), "states": dict(prev.get("states", {}))}
    api = LegiScan(KEY)
    changed = 0

    for code in STATES:
        print(f"\n=== {code} ({STATE_NAMES.get(code, code)}) ===")
        lst = api.op("getDatasetList", state=code)
        if not lst:
            print(f"  {code}: could not list datasets; keeping previous data")
            continue
        datasets = lst.get("datasetlist") or []
        session = pick_session(datasets)
        if not session:
            print(f"  {code}: no datasets available")
            continue
        print(f"  Session: {session.get('session_name')} (id {session.get('session_id')}, "
              f"hash {str(session.get('dataset_hash'))[:10]}…, date {session.get('dataset_date')})")

        old = out["states"].get(code) or {}
        if old.get("datasetHash") == session.get("dataset_hash") and old.get("legislators"):
            print(f"  {code}: dataset unchanged since last run -- skipping download (hash match)")
            continue

        ds = api.op("getDataset", id=session["session_id"], access_key=session["access_key"])
        if not ds or not (ds.get("dataset") or {}).get("zip"):
            print(f"  {code}: dataset download failed; keeping previous data")
            continue
        blob = base64.b64decode(ds["dataset"]["zip"])
        print(f"  Downloaded {len(blob) / 1048576:.1f} MB")
        data = parse_zip(blob)
        out["states"][code] = build_state(code, session, data)
        changed += 1
        time.sleep(1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nWrote {OUT} ({os.path.getsize(OUT) / 1048576:.1f} MB); "
          f"{changed} state(s) refreshed; API calls this run: {api.calls}")


if __name__ == "__main__":
    main()
