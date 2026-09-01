#!/usr/bin/env python3
"""
trades.py — stock-trade disclosure filings (STOCK Act) per member.

Source (official, no key): the Clerk of the House publishes a daily ZIP of
every financial disclosure filing, with an XML index:

  https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.zip
    -> {YEAR}FD.xml  with one record per filing:
       Prefix, Last, First, Suffix, FilingType, StateDst, Year, FilingDate, DocID

  FilingType 'P' = Periodic Transaction Report (a stock-trade disclosure).
  Each PTR's PDF lives at:
  https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{YEAR}/{DocID}.pdf

We match filings to members by StateDst (e.g. "TX05"; at-large is "00"),
which is exact for the House -- one representative per district -- with a
last-name check as a guard.

What this DOES: count each Representative's trade disclosures this Congress,
record the latest date, and link every filing PDF.

What this deliberately does NOT do (v1): parse the PDFs for tickers and
amounts. Disclosures give amount RANGES, never gains; and PDF text order is
notoriously chaotic. That is a separate, fragile job -- v2 once this plumbing
is proven. We also never claim "profits": nobody can honestly compute them.

Senate: efdsearch.senate.gov is behind an anti-automation gate. Senators get
a clear note and a link to the Senate's own search.
"""

import io
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

BASE = "https://disclosures-clerk.house.gov/public_disc"
SENATE_SEARCH = "https://efdsearch.senate.gov/search/"
RECENT_FILINGS = 10


def _fetch_index(year: int) -> Optional[List[Dict[str, str]]]:
    """Download {year}FD.zip and parse the XML index into dict rows."""
    url = f"{BASE}/financial-pdfs/{year}FD.zip"
    try:
        r = requests.get(url, timeout=120,
                         headers={"User-Agent": "congress-tracker/1.0"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  [trades] fetch failed for {year}: {e}", file=sys.stderr)
        return None

    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
        if not xml_name:
            print(f"  [trades] no XML in {year}FD.zip; entries: {zf.namelist()}")
            return None
        root = ET.fromstring(zf.read(xml_name))
    except Exception as e:
        print(f"  [trades] could not parse {year} index: {e}", file=sys.stderr)
        return None

    rows = []
    for rec in root:
        row = {child.tag.strip(): (child.text or "").strip() for child in rec}
        if row:
            rows.append(row)
    return rows


def _parse_date(s: str) -> Optional[str]:
    """'1/12/2026' -> '2026-01-12' (ISO), or None."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def add_trades(members: List[Dict[str, Any]], congress: int) -> bool:
    """
    Attach STOCK Act filing summaries. Mutates members in place.
    Covers the two calendar years of the current Congress.
    """
    year_now = datetime.now(timezone.utc).year
    # Congress N spans (odd year, even year); derive from the number.
    first_year = 2025 + 2 * (congress - 119)
    years = [y for y in (first_year, first_year + 1) if y <= year_now]

    print(f"Fetching House stock-trade disclosures (years {years})...")

    all_rows: List[Dict[str, str]] = []
    dumped = False
    for y in years:
        rows = _fetch_index(y)
        if rows is None:
            print(f"  {y}: index unavailable")
            continue
        if not dumped and rows:
            dumped = True
            print("\n  [debug] index record keys:", list(rows[0].keys()))
            print("  [debug] first record:", rows[0], "\n")
        ptrs = [r for r in rows if (r.get("FilingType") or "").upper() == "P"]
        print(f"  {y}: {len(rows)} filings, {len(ptrs)} periodic transaction reports")
        all_rows.extend(ptrs)

    # Index PTRs by StateDst, de-duplicated by DocID (a filing should never
    # appear twice, but the cost of guarding is zero).
    by_seat: Dict[str, List[Dict[str, Any]]] = {}
    seen_docs = set()
    for r in all_rows:
        seat = (r.get("StateDst") or "").upper()
        doc = r.get("DocID") or ""
        if not seat or (doc and doc in seen_docs):
            continue
        if doc:
            seen_docs.add(doc)
        year = r.get("Year") or ""
        by_seat.setdefault(seat, []).append({
            "docId": doc,
            "filingDate": _parse_date(r.get("FilingDate") or "") or r.get("FilingDate"),
            "year": year,
            "last": (r.get("Last") or "").strip().lower(),
            "url": f"{BASE}/ptr-pdfs/{year}/{doc}.pdf" if year and doc else None,
        })

    house_hits = 0
    for m in members:
        if m.get("chamber") != "House":
            m["trades"] = {
                "chamber": "Senate",
                "ptrCount": None,
                "note": ("Senate trade disclosures are published at "
                         "efdsearch.senate.gov, which blocks automated access. "
                         "Search there by name."),
                "sourceUrl": SENATE_SEARCH,
                "source": "U.S. Senate Electronic Financial Disclosure",
            }
            continue

        code = (m.get("stateCode") or "").upper()
        dist = m.get("district")
        try:
            dist_n = int(dist) if dist is not None else 0
        except (TypeError, ValueError):
            dist_n = 0
        seat = f"{code}{dist_n:02d}"

        filings = by_seat.get(seat, [])
        # Guard against a mid-term seat change: prefer rows whose last name
        # matches this member; fall back to all rows for the seat.
        last = (m.get("name") or "").split()[-1].lower().strip(".,")
        matched = [
            f for f in filings
            if f["last"] and (f["last"] in last or last in f["last"])
        ]
        if not matched:
            matched = filings

        matched.sort(key=lambda f: f["filingDate"] or "", reverse=True)
        if matched:
            house_hits += 1

        m["trades"] = {
            "chamber": "House",
            "ptrCount": len(matched),
            "latestFilingDate": matched[0]["filingDate"] if matched else None,
            "filings": [
                {"date": f["filingDate"], "url": f["url"], "docId": f["docId"]}
                for f in matched[:RECENT_FILINGS]
            ],
            "source": "Clerk of the U.S. House — Financial Disclosure Reports",
            "sourceUrl": "https://disclosures-clerk.house.gov/FinancialDisclosure",
            "note": ("Counts Periodic Transaction Reports filed this Congress. "
                     "Each report discloses one or more trades as amount ranges; "
                     "no dollar totals or gains are inferred."),
        }

    house_total = sum(1 for m in members if m.get("chamber") == "House")
    print("\n--- Trade disclosure data quality ---")
    print(f"  House members with at least one PTR: {house_hits}/{house_total}")
    print(f"  PTR filings indexed:                 {len(all_rows)}")
    print("  (Senators: linked to eFD search; not automatable)")
    return bool(all_rows)
