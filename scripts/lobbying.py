#!/usr/bin/env python3
"""
lobbying.py. Which organizations reported lobbying on each bill a member has
sponsored, from the official Lobbying Disclosure Act (LDA) database.

Source: LDA REST API, https://lda.gov/api/v1/filings/ (the former address,
lda.senate.gov, is kept as a fallback). Verified live response fields:
  filing_uuid, filing_type, filing_year, filing_period, filing_document_url,
  dt_posted, registrant{name}, client{name},
  lobbying_activities[]{general_issue_code, description}
Filters used: filing_year, filing_period, page_size; pagination via "next".
Auth: header "Authorization: Token <LDA_API_KEY>" (raises the rate limit
from 15 to 120 requests per minute).

RULES (missing over wrong):
  * Bill numbers are read only from the filing's own "specific lobbying
    issues" text, and only when written clearly (H.R. 1234, S. 567,
    H.Res. 89, S.J.Res. 12, ...). "S" without a period is never read as a
    Senate bill.
  * Only 2025-2026 filings are read, and matches attach only to 119th
    Congress bills. An activity that mentions an earlier Congress by name
    ("118th Congress") is skipped entirely.
  * Registrations (LD-1) are skipped; only activity reports count.
  So counts are "at least": lobbying described without a clear bill number
  is not counted.

Cost control: the database holds ~2 million filings. Work is split into
(year, quarter) chunks; a chunk is marked done once its quarter ended more
than 120 days ago (late amendments have settled). Recent chunks are re-read
each run. Progress is saved page by page, and the run stops on its own
before TIME_BUDGET_MIN, so the first big backfill simply continues on the
next run.

Files:
  data/lobbying_cache.json   working state (committed; not served)
  public/lobbying.json       what the site reads
"""

import os
import re
import sys
import json
import time
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Set

import requests

BASES = ["https://lda.gov/api/v1", "https://lda.senate.gov/api/v1"]
API_KEY = os.environ.get("LDA_API_KEY", "").strip()
YEARS = (2025, 2026)          # the 119th Congress
CONGRESS = 119
PERIODS = [("first_quarter", 3), ("second_quarter", 6),
           ("third_quarter", 9), ("fourth_quarter", 12)]
PAGE_SIZE = 25
REQUEST_DELAY = 0.55          # stays under 120 requests/minute
SETTLE_DAYS = 120
TIME_BUDGET_MIN = float(os.environ.get("LOBBYING_BUDGET_MIN", "300"))
MAX_LISTED = 30               # organizations listed per bill (count is complete)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "lobbying_cache.json")
OUT = os.path.join(ROOT, "public", "lobbying.json")
CONGRESS_DATA = os.path.join(ROOT, "public", "congress_data.json")

# Longest forms first; matched spans are blanked before the next pattern runs.
_BILL_PATTERNS = [
    ("hconres", r"\bH\.?\s?Con\.?\s?Res\.?\s?(\d{1,4})\b"),
    ("sconres", r"\bS\.?\s?Con\.?\s?Res\.?\s?(\d{1,4})\b"),
    ("hjres",   r"\bH\.?\s?J\.?\s?Res\.?\s?(\d{1,4})\b"),
    ("sjres",   r"\bS\.?\s?J\.?\s?Res\.?\s?(\d{1,4})\b"),
    ("hres",    r"\bH\.?\s?Res\.?\s?(\d{1,4})\b"),
    ("sres",    r"\bS\.?\s?Res\.?\s?(\d{1,4})\b"),
    ("hr",      r"\bH\.?\s?R\.?\s?(\d{1,5})\b"),
    ("s",       r"(?<![A-Za-z.])S\.\s?(\d{1,5})\b"),
]
_BILL_RES = [(k, re.compile(p, re.I)) for k, p in _BILL_PATTERNS]
_OTHER_CONGRESS = re.compile(r"\b(1[01]\d)(st|nd|rd|th)\s+Congress\b", re.I)


def extract_bills(text: str) -> Set[str]:
    """Bill keys like '119-hr1234' clearly written in a lobbying description."""
    if not text:
        return set()
    for m in _OTHER_CONGRESS.finditer(text):
        if int(m.group(1)) != CONGRESS:
            return set()
    found, work = set(), text
    for kind, rx in _BILL_RES:
        for m in rx.finditer(work):
            n = int(m.group(1))
            if n > 0:
                found.add(f"{CONGRESS}-{kind}{n}")
        work = rx.sub(lambda m: " " * len(m.group(0)), work)
    return found


def chunk_key(year: int, period: str) -> str:
    return f"{year}-{period}"


def chunk_settled(year: int, end_month: int, today: date) -> bool:
    end = date(year, end_month, 28)
    return (today - end).days > SETTLE_DAYS


def chunk_started(year: int, end_month: int, today: date) -> bool:
    return today >= date(year, end_month, 28)  # reports are filed after quarter end


class LDA:
    def __init__(self, key: str):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "congress-tracker/1.0", "Accept": "application/json"})
        if key:
            self.s.headers["Authorization"] = f"Token {key}"
        self.base = BASES[0]
        self.failures = 0

    def get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        for attempt in range(4):
            time.sleep(REQUEST_DELAY)
            try:
                r = self.s.get(url, params=params, timeout=(10, 60))
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After") or 60)
                    print(f"  [lda] rate limited; waiting {wait}s")
                    time.sleep(wait)
                    continue
                if r.status_code in (400, 404):
                    print(f"  [lda] HTTP {r.status_code} for {r.url}: {r.text[:200]}", file=sys.stderr)
                    self.failures += 1
                    return None
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                print(f"  [lda] request failed ({e}); attempt {attempt + 1}/4", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
        self.failures += 1
        return None

    def first_page(self, year: int, period: str) -> Optional[Dict]:
        params = {"filing_year": year, "filing_period": period, "page_size": PAGE_SIZE}
        for base in BASES:
            data = self.get(f"{base}/filings/", params)
            if data is not None:
                self.base = base
                return data
        return None


def load_cache() -> Dict:
    try:
        with open(CACHE) as fh:
            c = json.load(fh)
            c.setdefault("done", [])
            c.setdefault("bills", {})
            c.setdefault("partial", None)
            return c
    except FileNotFoundError:
        return {"done": [], "bills": {}, "partial": None}


def save_cache(cache: Dict) -> None:
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cache, fh, separators=(",", ":"))
    os.replace(tmp, CACHE)


def record_filing(cache: Dict, f: Dict) -> int:
    """Fold one filing into the cache. Returns bill matches recorded."""
    if str(f.get("filing_type") or "").upper() in ("RR", "RA"):
        return 0  # registrations, not activity reports
    client = ((f.get("client") or {}).get("name") or "").strip()
    registrant = ((f.get("registrant") or {}).get("name") or "").strip()
    if not client:
        return 0
    keys: Set[str] = set()
    for act in f.get("lobbying_activities") or []:
        keys |= extract_bills(act.get("description") or "")
    if not keys:
        return 0
    entry = {"c": client, "r": registrant if registrant.upper() != client.upper() else None,
             "u": f.get("filing_document_url"), "y": f.get("filing_year"),
             "p": f.get("filing_period"), "t": (f.get("dt_posted") or "")[:10]}
    for k in keys:
        orgs = cache["bills"].setdefault(k, {})
        prev = orgs.get(client.upper())
        if prev is None or (entry["t"] or "") >= (prev.get("t") or ""):
            orgs[client.upper()] = entry
    return len(keys)


PERIOD_LABEL = {"first_quarter": "Q1", "second_quarter": "Q2",
                "third_quarter": "Q3", "fourth_quarter": "Q4"}


def write_output(cache: Dict) -> int:
    universe: Set[str] = set()
    try:
        with open(CONGRESS_DATA) as fh:
            for m in json.load(fh).get("members", []):
                for b in m.get("bills") or []:
                    mm = re.search(r"/bill/(\d+)th-congress/([a-z]+)/(\d+)", b.get("sourceUrl") or "")
                    if mm and int(mm.group(1)) == CONGRESS:
                        universe.add(f"{CONGRESS}-{mm.group(2)}{mm.group(3)}")
    except FileNotFoundError:
        print("  congress_data.json not found; publishing nothing", file=sys.stderr)
    bills = {}
    for k in sorted(universe):
        orgs = cache["bills"].get(k)
        if not orgs:
            continue
        rows = sorted(orgs.values(), key=lambda e: e.get("t") or "", reverse=True)
        bills[k] = {"n": len(rows), "orgs": [
            [e["c"], e["r"], e["u"], f'{e["y"]} {PERIOD_LABEL.get(e["p"], "")}'.strip()]
            for e in rows[:MAX_LISTED]]}
    out = {"asOf": datetime.now(timezone.utc).date().isoformat(), "congress": CONGRESS,
           "completeQuarters": sorted(cache["done"]),
           "source": "Lobbying Disclosure Act reports, lda.gov",
           "sourceUrl": "https://lda.gov/filings/public/filing/search/",
           "bills": bills}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    os.replace(tmp, OUT)
    return len(bills)


def main() -> int:
    if not API_KEY:
        print("ERROR: LDA_API_KEY is not set.", file=sys.stderr)
        return 1
    start = time.monotonic()
    today = datetime.now(timezone.utc).date()
    cache = load_cache()
    api = LDA(API_KEY)
    pages_read = filings_read = 0
    out_of_time = False

    todo = [(y, p, mo) for y in YEARS for p, mo in PERIODS
            if chunk_started(y, mo, today) and chunk_key(y, p) not in cache["done"]]
    print(f"Lobbying: {len(todo)} quarter(s) to read: {[chunk_key(y, p) for y, p, _ in todo]}")

    for year, period, end_month in todo:
        key = chunk_key(year, period)
        partial = cache.get("partial") or {}
        if partial.get("chunk") == key and partial.get("next"):
            print(f"  {key}: resuming")
            data = api.get(partial["next"])
        else:
            print(f"  {key}: starting")
            data = api.first_page(year, period)
        if data is None:
            print(f"  {key}: could not read; will retry next run", file=sys.stderr)
            continue
        while True:
            results = data.get("results") or []
            for f in results:
                record_filing(cache, f)
            pages_read += 1
            filings_read += len(results)
            nxt = data.get("next")
            if not nxt:
                if chunk_settled(year, end_month, today):
                    cache["done"].append(key)
                cache["partial"] = None
                save_cache(cache)
                print(f"  {key}: finished ({data.get('count', '?')} filings in quarter)")
                break
            cache["partial"] = {"chunk": key, "next": nxt}
            if pages_read % 100 == 0:
                save_cache(cache)
                print(f"    {pages_read} pages, {filings_read} filings read this run")
            if (time.monotonic() - start) / 60 > TIME_BUDGET_MIN:
                out_of_time = True
                break
            data = api.get(nxt)
            if data is None:
                print(f"  {key}: page failed; will resume here next run", file=sys.stderr)
                break
        save_cache(cache)
        if out_of_time:
            print("  Time budget reached; the next run continues from here.")
            break

    published = write_output(cache)
    print("\n--- Lobbying ---")
    print(f"  Pages read this run:      {pages_read} ({filings_read} filings)")
    print(f"  Quarters complete:        {len(cache['done'])}")
    print(f"  Bills with lobbying (all 119th): {len(cache['bills'])}")
    print(f"  Sponsored bills published:{published:>6}")
    print(f"  Failed requests:          {api.failures}")
    if pages_read == 0 and not cache["bills"]:
        print("ERROR: no lobbying data could be read; not publishing.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
