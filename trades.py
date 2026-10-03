#!/usr/bin/env python3
"""
trades.py. stock-trade disclosure filings (STOCK Act) per member.

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

Senate: efdsearch.senate.gov requires accepting a terms agreement (a CSRF
token exchange) before its search works, then serves results from a JSON
endpoint. We do exactly what a person does -- load the page, accept, search --
and list every senator's PTRs since the start of this Congress. If that flow
ever breaks, senators degrade to a note plus a link to the Senate search.
"""

import io
import re
import sys
import html as htmlmod
import unicodedata
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
        r = requests.get(url, timeout=(10, 120),
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



SENATE_BASE = "https://efdsearch.senate.gov"
SENATE_PTR_TYPE = "11"      # report_types code for Periodic Transaction Report
SENATE_ANNUAL_TYPE = "7"    # report_types code for Annual Report
SENATE_FILER = "1"          # filer_types code for Senator


def _norm(s: str) -> str:
    """Lowercase, strip accents/punctuation, for name matching."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def _fetch_senate_ptrs(since_mmddyyyy: str,
                       report_type: str = SENATE_PTR_TYPE) -> Optional[List[Dict[str, str]]]:
    """
    Return a list of {first, last, title, url, date} for every Senate filing
    of `report_type` received since `since`, or None if the flow failed.
    """
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; congress-tracker/1.0)",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    })
    home = f"{SENATE_BASE}/search/home/"
    # (connect, read) timeouts: fail fast if the host silently drops us.
    T = (10, 25)
    try:
        r = sess.get(home, timeout=T)
        r.raise_for_status()
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
        if not m:
            print("  [senate] no csrf token on agreement page")
            return None
        token = m.group(1)
        # Accept the prohibition agreement (what the checkbox does).
        r2 = sess.post(home, data={"csrfmiddlewaretoken": token,
                                   "prohibition_agreement": "1"},
                       headers={"Referer": home}, timeout=T, allow_redirects=True)
        r2.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  [senate] agreement step failed: {e}", file=sys.stderr)
        return None

    csrf = sess.cookies.get("csrftoken") or token
    data_url = f"{SENATE_BASE}/search/report/data/"
    hdr = {"Referer": f"{SENATE_BASE}/search/", "X-CSRFToken": csrf,
           "X-Requested-With": "XMLHttpRequest"}

    rows: List[Dict[str, str]] = []
    start, length = 0, 100
    dumped = False
    MAX_PAGES = 15  # 1,500 PTRs is more than a Congress produces
    pages = 0
    while pages < MAX_PAGES:
        pages += 1
        form = {
            "draw": str(start // length + 1),
            "start": str(start), "length": str(length),
            "report_types": f"[{report_type}]",
            "filer_types": f"[{SENATE_FILER}]",
            "submitted_start_date": f"{since_mmddyyyy} 00:00:00",
            "submitted_end_date": "",
            "candidate_state": "", "senator_state": "", "office_id": "",
            "first_name": "", "last_name": "",
            "search[value]": "", "search[regex]": "false",
            "order[0][column]": "4", "order[0][dir]": "desc",
        }
        for i in range(5):
            form[f"columns[{i}][data]"] = str(i)
            form[f"columns[{i}][name]"] = ""
            form[f"columns[{i}][searchable]"] = "true"
            form[f"columns[{i}][orderable]"] = "true"
            form[f"columns[{i}][search][value]"] = ""
            form[f"columns[{i}][search][regex]"] = "false"
        try:
            r = sess.post(data_url, data=form, headers=hdr, timeout=T)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"  [senate] data request failed on page {pages}: {e}", file=sys.stderr)
            return rows or None  # partial results are still useful

        batch = payload.get("data") or []
        total = payload.get("recordsFiltered") or payload.get("recordsTotal")
        if not dumped:
            dumped = True
            print("  [debug] senate response keys:", list(payload.keys()),
                  "| total:", payload.get("recordsTotal"))
            if batch:
                print("  [debug] senate first row:", str(batch[0])[:300])
        for row in batch:
            if not isinstance(row, list) or len(row) < 5:
                continue
            first, last, _office, link_html, date = row[:5]
            href = re.search(r'href="([^"]+)"', link_html or "")
            title = re.sub(r"<[^>]+>", "", link_html or "").strip()
            rows.append({
                "first": htmlmod.unescape(first or "").strip(),
                "last": htmlmod.unescape(last or "").strip(),
                "title": htmlmod.unescape(title),
                "url": (SENATE_BASE + href.group(1)) if href else None,
                "date": _parse_date((date or "").strip()) or (date or "").strip(),
            })
        if len(batch) < length:
            break
        start += length
        if isinstance(total, int) and start >= total:
            break
    return rows


def _match_senator(members_senate: List[Dict], first: str, last: str) -> Optional[Dict]:
    """Match a filing's first/last to a senator; exact last + first/nick/initial."""
    nl = _norm(last)
    cands = [m for m in members_senate if _norm(m.get("lastName") or "") == nl]
    if not cands:
        # Hyphenated / multi-word surnames: try containment.
        cands = [m for m in members_senate
                 if nl and (nl in _norm(m.get("lastName") or "") or _norm(m.get("lastName") or "") in nl)]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    nf = _norm(first)
    for m in cands:
        for cand in (m.get("firstName"), m.get("nickname")):
            if cand and _norm(cand) == nf:
                return m
    for m in cands:
        f = _norm(m.get("firstName") or "")
        if f and nf and f[0] == nf[0]:
            return m
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
    all_annual_rows: List[Dict[str, str]] = []
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
        annuals = [r for r in rows if (r.get("FilingType") or "").upper() == "O"]
        print(f"  {y}: {len(rows)} filings, {len(ptrs)} periodic transaction reports, "
              f"{len(annuals)} annual reports")
        all_rows.extend(ptrs)
        all_annual_rows.extend(annuals)

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

    # Latest House annual report per seat (annual PDFs live under financial-pdfs).
    annual_by_seat: Dict[str, Dict[str, Any]] = {}
    for r in all_annual_rows:
        seat = (r.get("StateDst") or "").upper()
        year = r.get("Year") or ""; doc = r.get("DocID") or ""
        if not (seat and year and doc):
            continue
        d = _parse_date(r.get("FilingDate") or "") or ""
        cur = annual_by_seat.get(seat)
        if cur is None or d > (cur["date"] or ""):
            annual_by_seat[seat] = {
                "title": f"Annual financial disclosure, {year}",
                "date": d or None,
                "url": f"{BASE}/financial-pdfs/{year}/{doc}.pdf",
                "last": (r.get("Last") or "").strip().lower(),
            }

    # ---- Senate ----
    senators = [m for m in members if m.get("chamber") == "Senate"]
    since = f"01/01/{first_year}"
    print(f"Fetching Senate stock-trade disclosures (since {since})...")
    senate_rows = _fetch_senate_ptrs(since)
    senate_by_bioguide: Dict[str, List[Dict[str, Any]]] = {}
    unmatched = 0
    if senate_rows:
        for r in senate_rows:
            m = _match_senator(senators, r["first"], r["last"])
            if not m:
                unmatched += 1
                continue
            senate_by_bioguide.setdefault(m["bioguideId"], []).append(r)
        print(f"  Senate: {len(senate_rows)} PTRs, {unmatched} unmatched to a sitting senator")
    else:
        print("  Senate: fetch unavailable; senators will link to eFD search")

    senate_annual_by_bioguide: Dict[str, Dict[str, Any]] = {}
    if senate_rows is not None:
        annual_rows = _fetch_senate_ptrs(since, SENATE_ANNUAL_TYPE) or []
        # Sanity: if titles don't look like annual reports, the type code is
        # wrong -- log it and skip rather than show garbage.
        if annual_rows and not any("annual" in (r["title"] or "").lower() for r in annual_rows[:20]):
            print("  [senate] annual-report type code returned unexpected titles; skipping. "
                  f"Sample: {annual_rows[0]['title'][:60]}")
            annual_rows = []
        for r in annual_rows:
            m = _match_senator(senators, r["first"], r["last"])
            if not m:
                continue
            cur = senate_annual_by_bioguide.get(m["bioguideId"])
            if cur is None or (r["date"] or "") > (cur["date"] or ""):
                senate_annual_by_bioguide[m["bioguideId"]] = {
                    "title": r["title"], "date": r["date"], "url": r["url"],
                }
        print(f"  Senate: {len(annual_rows)} annual reports, "
              f"{len(senate_annual_by_bioguide)} senators matched")

    house_hits = 0
    senate_hits = 0
    for m in members:
        if m.get("chamber") != "House":
            rows = senate_by_bioguide.get(m["bioguideId"])
            if senate_rows is None:
                m["trades"] = {
                    "chamber": "Senate", "ptrCount": None,
                    "note": ("Senate trade disclosures live at efdsearch.senate.gov. "
                             "Automated retrieval was unavailable on this run; "
                             "search there by name."),
                    "sourceUrl": SENATE_SEARCH,
                    "source": "U.S. Senate Electronic Financial Disclosure",
                }
                continue
            rows = sorted(rows or [], key=lambda r: r["date"] or "", reverse=True)
            if rows:
                senate_hits += 1
            m["trades"] = {
                "chamber": "Senate",
                "ptrCount": len(rows),
                "latestFilingDate": rows[0]["date"] if rows else None,
                "filings": [{"date": r["date"], "url": r["url"], "docId": r["url"]}
                            for r in rows[:RECENT_FILINGS]],
                "source": "U.S. Senate Electronic Financial Disclosure",
                "sourceUrl": SENATE_SEARCH,
                "annual": senate_annual_by_bioguide.get(m["bioguideId"]),
                "note": ("Counts Periodic Transaction Reports filed this Congress. "
                         "Each report discloses one or more trades as amount ranges; "
                         "no dollar totals or gains are inferred."),
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

        annual = annual_by_seat.get(seat)
        if annual and annual.get("last") and not (annual["last"] in last or last in annual["last"]):
            annual = None  # seat changed hands; don't attribute a predecessor's report
        m["trades"] = {
            "chamber": "House",
            "ptrCount": len(matched),
            "latestFilingDate": matched[0]["filingDate"] if matched else None,
            "annual": ({"title": annual["title"], "date": annual["date"], "url": annual["url"]}
                       if annual else None),
            "filings": [
                {"date": f["filingDate"], "url": f["url"], "docId": f["docId"]}
                for f in matched[:RECENT_FILINGS]
            ],
            "source": "Clerk of the U.S. House. Financial Disclosure Reports",
            "sourceUrl": "https://disclosures-clerk.house.gov/FinancialDisclosure",
            "note": ("Counts Periodic Transaction Reports filed this Congress. "
                     "Each report discloses one or more trades as amount ranges; "
                     "no dollar totals or gains are inferred."),
        }

    house_total = sum(1 for m in members if m.get("chamber") == "House")
    print("\n--- Trade disclosure data quality ---")
    print(f"  House members with at least one PTR:   {house_hits}/{house_total}")
    print(f"  House PTR filings indexed:             {len(all_rows)}")
    print(f"  Senators with at least one PTR:        {senate_hits}/{len(senators)}")
    print(f"  Senate PTR filings indexed:            {len(senate_rows or [])}")
    return bool(all_rows) or bool(senate_rows)
