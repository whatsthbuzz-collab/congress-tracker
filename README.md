# Congress Tracker

Sourced, nonpartisan facts about the people who represent you: every member of Congress, every state legislator, and the 2026 federal races on the ballot.

**Live site:** https://whatsthbuzz-collab.github.io/congress-tracker/

Candidate and member facts, not recommendations. Every figure links back to its official source. Where a fact cannot be sourced, the site shows nothing rather than a guess.

---

## What's on the site

**Federal**
- All current members of Congress, including non-voting delegates
- Sponsored bills with status, topic, Congressional Research Service (CRS) summaries, and executive order titles where a bill references one
- House and Senate voting records: votes with party, votes missed, recent roll calls
- Campaign finance from the Federal Election Commission (FEC): total raised, share from PACs, cash on hand
- Stock trade disclosures (Periodic Transaction Reports)
- Committee assignments, party comparisons, and shareable member links
- District finder: enter a zip code, city, or address, or use your location

**State Legislatures**
- Legislators in all 50 states, with sponsored bills, bill status, topics, and voting records

**Elections**
- Side-by-side candidate cards for selected 2026 U.S. Senate and House races
- FEC finance totals, named PAC donors tagged with the FEC's committee type, background facts, photos, and campaign links

**How these numbers are made**
- A methodology page, linked in the site footer, defines every figure and its source.

---

## Editorial rules

- **Facts, not recommendations.** No scores, ratings, or endorsements.
- **Every claim sourced.** Each figure links to the official record it came from.
- **Missing over wrong.** If data is unavailable or unverified, the site shows "n/a" or nothing.
- **Even-handed elections cards.** Both candidates in a race get a photo and a campaign link, or neither does. The build refuses to run if this is violated.
- **Licensed photos only.** Candidate photos are public domain government portraits or freely licensed images from Wikimedia Commons, credited on the page.

---

## Data sources

| Data | Source | License / terms |
|---|---|---|
| Member roster, committees | [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) | Public domain |
| Bills, laws, House roll calls | [Congress.gov API](https://api.congress.gov/) | Public domain |
| Bill summaries | Congressional Research Service, via Congress.gov | Public domain |
| Executive order titles | [Federal Register API](https://www.federalregister.gov/developers/api/v1) | Public domain |
| Senate roll calls | [senate.gov XML](https://www.senate.gov/general/XML.htm) | Public domain |
| Campaign finance | [OpenFEC API](https://api.open.fec.gov/) | Public domain |
| Stock trade disclosures | [House Clerk](https://disclosures-clerk.house.gov/) and [Senate eFD](https://efdsearch.senate.gov/) | Public records |
| State legislatures | [LegiScan](https://legiscan.com/) bulk datasets | CC BY 4.0, credited on the site |
| District finder | [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/) and [U.S. Census geocoder](https://geocoding.geo.census.gov/) | Lookups run in the visitor's browser; the site never sees or stores locations |
| Member photos | [unitedstates/images](https://github.com/unitedstates/images) | Public domain |
| Election candidate photos | Wikimedia Commons, per-photo license | Credited on each election page |

---

## Automated updates

Data refreshes run on GitHub Actions. Each pipeline exits with an error instead of publishing if its output fails quality checks, so the previous good data stays live.

| Workflow | Script | Schedule (UTC) |
|---|---|---|
| Update Congressional Data | `scripts/fetch_congress_data.py` | Daily, 02:00 |
| Update Elections Data | `scripts/elections.py` | Daily, 10:00 |
| Update State Data | `scripts/state_legislature.py` | Mondays, 09:00 |
| Build and Deploy to GitHub Pages | `npm run build` | On every push to `main`, and after data updates |

All workflows can also be run manually from the **Actions** tab.

### Required repository secrets

| Secret | Used by | Get one at |
|---|---|---|
| `CONGRESS_API_KEY` | Congressional data | https://api.congress.gov/sign-up/ |
| `FEC_API_KEY` | Congressional data, elections | https://api.data.gov/signup/ |
| `LEGISCAN_API_KEY` | State data | https://legiscan.com/legiscan |

---

## Repository layout

```
.github/workflows/   Scheduled data updates and deployment
public/              Generated data (JSON), committed by the workflows
  congress_data.json
  state/             One file per state, plus index.json
  elections/         One file per race, plus index.json
scripts/             Python data pipelines
src/                 React front end (Vite)
```

---

## Local development

Requires Node 20 and Python 3.11.

```bash
git clone https://github.com/whatsthbuzz-collab/congress-tracker.git
cd congress-tracker
npm install
pip install requests pyyaml

# Optional: refresh data locally (set the API keys above as environment variables first)
python scripts/fetch_congress_data.py
python scripts/elections.py
python scripts/state_legislature.py

npm run dev
```

---

## Adding an election race

Races are configured in the `RACES` list at the top of `scripts/elections.py`.

1. Verify both candidates are the current nominees.
2. Look up each candidate's FEC candidate ID on [fec.gov](https://www.fec.gov/data/). House races can omit committee IDs; the script looks them up from the candidate ID.
3. Source every background fact and add its link.
4. Add photos only if both candidates have public domain or freely licensed photos, and campaign links only if both have confirmed campaign sites.
5. Commit, then run **Update Elections Data** from the Actions tab.
