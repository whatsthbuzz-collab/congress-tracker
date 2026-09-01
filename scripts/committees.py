#!/usr/bin/env python3
"""
committees.py — add committee assignments to each member.

Source: unitedstates/congress-legislators (public domain), same family as
the member roster. Two files, no key required:

  committees-current.json            all current committees + subcommittees
  committee-membership-current.json  {committee_id: [ {bioguide, title,
                                       rank, party}, ... ]}

Both are keyed by Bioguide ID, so the join is exact.

Subcommittees are identified by parent ID + 2-digit suffix (SSCM33 is a
subcommittee of SSCM). We fold them under their parent so a profile reads
"Commerce, Science & Transportation — Chairman" rather than seventeen
near-duplicate lines. Where a member holds a leadership title on a
subcommittee only, we note it.

Per member this adds:
  committees: [ {id, name, chamber, role, url, subcommittees:[...]}, ... ]
  Sorted leadership-first, then alphabetical.
"""

import sys
from typing import Any, Dict, List

import requests

BASE = ("https://raw.githubusercontent.com/unitedstates/"
        "congress-legislators/gh-pages/")
COMMITTEES_URL = BASE + "committees-current.json"
MEMBERSHIP_URL = BASE + "committee-membership-current.json"

LEADERSHIP_TITLES = {"Chairman", "Chair", "Chairwoman", "Ranking Member",
                     "Vice Chairman", "Vice Chair", "Co-Chairman", "Co-Chair"}


def _shorten(name: str) -> str:
    """'House Committee on Agriculture' -> 'Agriculture'."""
    for prefix in ("House Committee on ", "Senate Committee on ",
                   "Joint Committee on ", "House ", "Senate ", "Joint "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if name.lower().startswith("the "):
        name = name[4:]
    return name


def add_committees(members: List[Dict[str, Any]]) -> bool:
    print("Fetching committee assignments...")
    try:
        comms = requests.get(COMMITTEES_URL, timeout=60).json()
        membership = requests.get(MEMBERSHIP_URL, timeout=60).json()
    except Exception as e:  # network or JSON failure -- don't kill the run
        print(f"  Committee fetch failed: {e}", file=sys.stderr)
        for m in members:
            m["committees"] = []
        return False

    # Build parent lookup: id -> {name, chamber, url, subs: {subid: name}}
    parents: Dict[str, Dict] = {}
    for c in comms:
        pid = c.get("thomas_id")
        if not pid:
            continue
        subs = {}
        for s in c.get("subcommittees") or []:
            sid = s.get("thomas_id")
            if sid:
                subs[pid + sid] = s.get("name") or ""
        parents[pid] = {
            "id": pid,
            "name": _shorten(c.get("name") or pid),
            "fullName": c.get("name") or pid,
            "chamber": (c.get("type") or "").capitalize(),
            "url": c.get("url"),
            "subs": subs,
        }

    # bioguide -> {parent_id -> assignment}
    per_member: Dict[str, Dict[str, Dict]] = {}

    for cid, roster in membership.items():
        if not isinstance(roster, list):
            continue
        # Resolve to parent: exact parent, or strip 2-digit suffix.
        if cid in parents:
            pid, sub_name = cid, None
        elif cid[:-2] in parents and cid[-2:].isdigit():
            pid = cid[:-2]
            sub_name = parents[pid]["subs"].get(cid, "")
        else:
            continue  # unknown committee id

        p = parents[pid]
        for entry in roster:
            bid = entry.get("bioguide")
            if not bid:
                continue
            title = (entry.get("title") or "").strip()
            slot = per_member.setdefault(bid, {}).setdefault(pid, {
                "id": pid,
                "name": p["name"],
                "fullName": p["fullName"],
                "chamber": p["chamber"],
                "url": p["url"],
                "role": "Member",
                "subcommittees": [],
            })
            if sub_name is None:
                # Full-committee membership: this sets the headline role.
                if title in LEADERSHIP_TITLES:
                    slot["role"] = title
            else:
                # Subcommittee: record it; note leadership if any.
                label = sub_name
                if title in LEADERSHIP_TITLES:
                    label = f"{sub_name} ({title})"
                if label and label not in slot["subcommittees"]:
                    slot["subcommittees"].append(label)

    def sort_key(c):
        lead = 0 if c["role"] in LEADERSHIP_TITLES else 1
        return (lead, c["name"])

    enriched = 0
    for m in members:
        assignments = list(per_member.get(m["bioguideId"], {}).values())
        assignments.sort(key=sort_key)
        m["committees"] = assignments
        if assignments:
            enriched += 1

    print("\n--- Committee data quality ---")
    print(f"  Members with committees: {enriched}/{len(members)}")
    return True
