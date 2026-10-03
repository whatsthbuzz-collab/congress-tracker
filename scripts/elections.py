#!/usr/bin/env python3
"""
elections.py: federal candidate data for upcoming races.

Facts about candidates, not a recommendation engine. Each candidate gets what
the FEC reports (money) plus a short set of hand-sourced facts, each with a
citation link. RACES below is hand-maintained; every FEC ID in it was
verified against fec.gov.

FEC field and endpoint notes (each one was a real bug at some point):
  * Cash on hand on /committee/{id}/totals/ is `last_cash_on_hand_end_period`.
    The unprefixed `cash_on_hand_end_period` exists only on /reports/ and
    silently reads as None, which looks like "no data".
  * The /schedules/schedule_a/by_contributor/ aggregate endpoint no longer
    exists. Named donors come from itemized /schedules/schedule_a/ with
    contributor_type=committee and seek pagination (echo last_indexes).
  * Only Form 3 lines 11B (party) and 11C (PACs) count as donors, so
    transfers from a candidate's own joint-fundraising committees (line 12)
    are never shown as outside money.
  * Donors are fetched largest-first (sort=-contribution_receipt_amount);
    date order with a page cap buried major PAC checks.
  * House races may list only a verified candidate ID; their committees are
    looked up from /candidate/{id}/committees/ at run time.

If every candidate comes back without finance data and requests failed, the
script exits non-zero so the workflow never commits an all-empty dataset.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

FEC_BASE = "https://api.open.fec.gov/v1"
FEC_API_KEY = os.environ.get("FEC_API_KEY", "").strip()
REQUEST_DELAY = 0.5
OUT_DIR = os.path.join("public", "elections")
INDEX = os.path.join(OUT_DIR, "index.json")

TOP_PAC_DONORS = 8
MAX_SCHED_A_PAGES = 15
DONOR_LINES = {"11B", "11C"}

# ActBlue and WinRed are registered with the FEC as conduits for bundled
# individual donations; labeling them "PAC" would mislead.
CONDUIT_COMMITTEE_IDS = {"C00401224", "C00694323"}
CONDUIT_LABEL = "conduit - bundled individual donations"


def current_cycle() -> int:
    y = datetime.now(timezone.utc).year
    return y if y % 2 == 0 else y + 1


# Race configuration. Every non-FEC fact carries its own source link.
# To add a race: copy a block, verify the FEC candidate ID on fec.gov, and
# source every fact. Both candidates in a race get photos, or neither does.
RACES: List[Dict[str, Any]] = [{'id': 'tx-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Texas',
  'stateCode': 'TX',
  'electionDate': '2026-11-03',
  'seatNote': 'Open seat: Sen. John Cornyn did not win renomination.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Texas',
  'candidates': [{'name': 'James Talarico',
                  'party': 'Democratic',
                  'fecId': 'S6TX00479',
                  'committees': ['C00919084'],
                  'currentOffice': 'Texas House of Representatives, District 50',
                  'stateProfile': {'code': 'TX', 'chamber': 'House', 'district': '50'},
                  'background': 'Public school teacher before entering the Texas Legislature in '
                                '2019; B.A. in Government, University of Texas at Austin; M.Ed., '
                                'Harvard University.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/James_Talarico',
                  'campaignSiteUrl': 'https://jamestalarico.com/issues/',
                  'facts': [{'label': 'Born', 'value': 'Round Rock, Texas'},
                            {'label': 'High school', 'value': 'McNeil High School'},
                            {'label': "Bachelor's", 'value': 'University of Texas at Austin'},
                            {'label': 'Graduate', 'value': 'Harvard University'},
                            {'label': 'Profession', 'value': 'Educator'},
                            {'label': 'Current office pay',
                             'value': '$7,200/yr + $221/day per diem'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/James_Talarico_Press_Conference_3x4_(cropped).jpg?width=240',
                            'credit': 'Antonioaesparza, CC BY-SA 4.0, via Wikimedia Commons',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:James_Talarico_Press_Conference_3x4_(cropped).jpg'},
                  'incumbent': False},
                 {'name': 'Ken Paxton',
                  'party': 'Republican',
                  'fecId': 'S6TX00388',
                  'committees': ['C00901918', 'C00930446'],
                  'currentOffice': 'Texas Attorney General',
                  'stateProfile': None,
                  'background': 'Texas Attorney General since 2015; previously served in the Texas '
                                'House (2003-2013) and Texas Senate (2013-2015).',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Ken_Paxton',
                  'campaignSiteUrl': 'https://www.kenpaxton.com/issues',
                  'facts': [{'label': 'Born', 'value': 'Minot, North Dakota'},
                            {'label': "Bachelor's", 'value': 'Baylor University'},
                            {'label': 'Graduate',
                             'value': 'M.B.A., Baylor; J.D., University of Virginia'},
                            {'label': 'Profession', 'value': 'Attorney'},
                            {'label': 'Current office pay', 'value': '$153,750/yr'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Ken_Paxton_2024_(3x4_cropped).jpg?width=240',
                            'credit': 'Gage Skidmore, CC BY-SA 2.0, via Wikimedia Commons',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Ken_Paxton_2024_(3x4_cropped).jpg'},
                  'incumbent': False}]},
 {'id': 'ga-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Georgia',
  'stateCode': 'GA',
  'electionDate': '2026-11-03',
  'seatNote': 'Sen. Jon Ossoff (D) is seeking a second term. Georgia holds a Dec. 1 runoff if no '
              'candidate wins a majority on Nov. 3.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Georgia',
  'candidates': [{'name': 'Jon Ossoff',
                  'party': 'Democratic',
                  'fecId': 'S8GA00180',
                  'committees': ['C00718866'],
                  'currentOffice': 'U.S. Senator, Georgia',
                  'stateProfile': None,
                  'background': 'U.S. senator since 2021; before politics, ran an investigative '
                                'journalism company. Seeking a second term.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Jon_Ossoff',
                  'campaignSiteUrl': 'https://electjon.com/bio/',
                  'facts': [{'label': 'Born', 'value': 'Atlanta, Georgia'},
                            {'label': "Bachelor's", 'value': 'Georgetown University'},
                            {'label': 'Graduate', 'value': 'London School of Economics'},
                            {'label': 'Profession', 'value': 'Media executive'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Jon_Ossoff_Senate_Portrait_2021_(cropped).jpg?width=240',
                            'credit': 'U.S. Senate Photographic Studio, public domain',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Jon_Ossoff_Senate_Portrait_2021_(cropped).jpg'},
                  'incumbent': True},
                 {'name': 'Mike Collins',
                  'party': 'Republican',
                  'fecId': 'S6GA00390',
                  'committees': ['C00544684'],
                  'currentOffice': 'U.S. Representative, GA-10',
                  'stateProfile': None,
                  'background': "U.S. representative for Georgia's 10th district since 2023; "
                                'founded a trucking company; son of former U.S. Rep. Mac Collins.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Mike_Collins_(Georgia)',
                  'campaignSiteUrl': 'https://mikecollinsga.com/about/',
                  'facts': [{'label': 'Born', 'value': 'Jackson, Georgia'},
                            {'label': "Bachelor's", 'value': 'Georgia State University'},
                            {'label': 'Profession', 'value': 'Businessman (trucking)'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Rep._Mike_Collins_official_photo,_118th_Congress.jpg?width=240',
                            'credit': 'United States Congress, public domain',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Rep._Mike_Collins_official_photo,_118th_Congress.jpg'},
                  'incumbent': False}]},
 {'id': 'mi-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Michigan',
  'stateCode': 'MI',
  'electionDate': '2026-11-03',
  'seatNote': 'Open seat: Sen. Gary Peters (D) is retiring.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Michigan',
  'candidates': [{'name': 'Abdul El-Sayed',
                  'party': 'Democratic',
                  'fecId': 'S6MI00418',
                  'committees': ['C00902668'],
                  'currentOffice': 'Former Wayne County Health Director',
                  'stateProfile': None,
                  'background': 'Physician and epidemiologist; former Detroit health commissioner '
                                'and Wayne County health director; candidate for governor in 2018.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Abdul_El-Sayed',
                  'campaignSiteUrl': 'https://abdulforsenate.com/priorities/',
                  'facts': [{'label': 'Born', 'value': 'Southeast Michigan'},
                            {'label': "Bachelor's", 'value': 'University of Michigan'},
                            {'label': 'Graduate',
                             'value': 'M.D., Columbia; D.Phil., Oxford (Rhodes Scholar)'},
                            {'label': 'Profession', 'value': 'Physician & epidemiologist'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Abdul_El-Sayed.jpg?width=240',
                            'credit': 'Kenneth C. Zirkel, CC BY-SA 4.0, via Wikimedia Commons',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Abdul_El-Sayed.jpg'},
                  'incumbent': False},
                 {'name': 'Mike Rogers',
                  'party': 'Republican',
                  'fecId': 'S4MI00595',
                  'committees': ['C00849810', 'C00892026'],
                  'currentOffice': 'Former U.S. Representative, MI-08',
                  'stateProfile': None,
                  'background': 'U.S. representative from Michigan (2001-2015), chairing the House '
                                'Intelligence Committee; former FBI special agent; Republican '
                                'nominee for this seat in 2024.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Mike_Rogers_(Michigan)',
                  'campaignSiteUrl': 'https://rogersforsenate.com/what-michiganders-need-to-know',
                  'facts': [{'label': 'Born', 'value': 'Livonia, Michigan'},
                            {'label': "Bachelor's", 'value': 'Adrian College'},
                            {'label': 'Profession', 'value': 'Former FBI special agent'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Mike-Rogers-Head-Shot-2_(3x4_cropped).jpg?width=240',
                            'credit': 'United States Congress, public domain',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Mike-Rogers-Head-Shot-2_(3x4_cropped).jpg'},
                  'incumbent': False}]},
 {'id': 'nc-sen-2026',
  'office': 'U.S. Senate',
  'state': 'North Carolina',
  'stateCode': 'NC',
  'electionDate': '2026-11-03',
  'seatNote': 'Open seat: Sen. Thom Tillis (R) is not seeking a third term.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_North_Carolina',
  'candidates': [{'name': 'Roy Cooper',
                  'party': 'Democratic',
                  'fecId': 'S6NC00407',
                  'committees': ['C00913566'],
                  'currentOffice': 'Former Governor of North Carolina',
                  'stateProfile': None,
                  'background': 'Governor of North Carolina (2017-2025); state attorney general '
                                '(2001-2017); previously a state legislator.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Roy_Cooper',
                  'campaignSiteUrl': 'https://roycooper.com/about/',
                  'facts': [{'label': 'Born', 'value': 'Nashville, North Carolina'},
                            {'label': "Bachelor's",
                             'value': 'University of North Carolina at Chapel Hill'},
                            {'label': 'Graduate', 'value': 'J.D., University of North Carolina'},
                            {'label': 'Profession', 'value': 'Attorney'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Gov._Cooper_Cropped.jpg?width=240',
                            'credit': 'via Wikimedia Commons',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Gov._Cooper_Cropped.jpg'},
                  'incumbent': False},
                 {'name': 'Michael Whatley',
                  'party': 'Republican',
                  'fecId': 'S6NC00415',
                  'committees': ['C00913996', 'C00909416'],
                  'currentOffice': 'Former RNC Chairman',
                  'stateProfile': None,
                  'background': 'Chair of the Republican National Committee (2024-2025) and the '
                                'North Carolina Republican Party (2019-2024); attorney; has not '
                                'previously held elected office.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Michael_Whatley',
                  'campaignSiteUrl': 'https://michaelwhatley.com/issues/',
                  'facts': [{'label': 'Born', 'value': 'North Carolina'},
                            {'label': "Bachelor's", 'value': 'UNC Charlotte'},
                            {'label': 'Graduate',
                             'value': 'M.A., Wake Forest; M.A. & J.D., Notre Dame'},
                            {'label': 'Profession', 'value': 'Attorney'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Michael_Whatley_(54351730621)_(cropped).jpg?width=240',
                            'credit': 'Gage Skidmore, CC BY-SA 2.0, via Wikimedia Commons',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Michael_Whatley_(54351730621)_(cropped).jpg'},
                  'incumbent': False}]},
 {'id': 'me-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Maine',
  'stateCode': 'ME',
  'electionDate': '2026-11-03',
  'seatNote': 'Sen. Susan Collins (R) is seeking a sixth term. Primary winner Graham Platner '
              'withdrew in July; Maine Democrats nominated Troy Jackson at a special convention on '
              'July 25.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Maine',
  'candidates': [{'name': 'Troy Jackson',
                  'party': 'Democratic',
                  'fecId': 'S6ME00464',
                  'committees': ['C00955609'],
                  'currentOffice': 'Former Maine Senate President',
                  'stateProfile': None,
                  'background': 'Fifth-generation logger from northern Maine; served in the Maine '
                                'Senate 2008-2014 and 2016-2024, as its president from 2018 to '
                                '2024; candidate for governor earlier in 2026.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Troy_Jackson_(Maine)',
                  'financeNote': 'Committee registered July 2026; its first FEC report is due Oct. '
                                 '15, 2026.',
                  'campaignSiteUrl': 'https://www.jacksonformaine.com/priorities',
                  'facts': [{'label': 'Profession', 'value': 'Logger'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Senate_President_Troy_Jackson_(cropped).png?width=240',
                            'credit': 'ArenLeBrun, via Wikimedia Commons',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Senate_President_Troy_Jackson_(cropped).png'},
                  'incumbent': False},
                 {'name': 'Susan Collins',
                  'party': 'Republican',
                  'fecId': 'S6ME00159',
                  'committees': ['C00314575'],
                  'currentOffice': 'U.S. Senator, Maine',
                  'stateProfile': None,
                  'background': 'U.S. senator since 1997; chairs the Senate Appropriations '
                                'Committee. Seeking a sixth term.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Susan_Collins_(Maine)',
                  'campaignSiteUrl': 'https://susancollins.com/track-record/',
                  'facts': [{'label': 'Born', 'value': 'Caribou, Maine'},
                            {'label': "Bachelor's", 'value': 'St. Lawrence University'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Senator_Susan_Collins_2014_official_portrait.jpg?width=240',
                            'credit': 'U.S. Congress, public domain',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Senator_Susan_Collins_2014_official_portrait.jpg'},
                  'incumbent': True}]},
 {'id': 'sc-sen-2026',
  'office': 'U.S. Senate',
  'state': 'South Carolina',
  'stateCode': 'SC',
  'electionDate': '2026-11-03',
  'seatNote': 'Sen. Lindsey Graham (R) died July 11. Gov. Henry McMaster appointed Darline Graham, '
              'his sister, to the seat; she won the Aug. 25 special primary runoff to seek a full '
              'term.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_South_Carolina',
  'candidates': [{'name': 'Annie Andrews',
                  'party': 'Democratic',
                  'fecId': 'S6SC04239',
                  'committees': ['C00906024'],
                  'currentOffice': 'Pediatrician',
                  'stateProfile': None,
                  'background': 'Pediatrician who spent 15 years on the faculty of the Medical '
                                'University of South Carolina; Democratic nominee for a U.S. House '
                                'seat in 2022.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Annie_Andrews',
                  'campaignSiteUrl': 'https://drannieandrews.com/platform/',
                  'facts': [{'label': 'Born', 'value': 'Paducah, Kentucky'},
                            {'label': 'Profession', 'value': 'Pediatrician'}],
                  'incumbent': False},
                 {'name': 'Darline Graham',
                  'party': 'Republican',
                  'fecId': '',
                  'committees': [],
                  'currentOffice': 'U.S. Senator, South Carolina (appointed)',
                  'stateProfile': None,
                  'background': 'Appointed to the Senate in July 2026 to fill the seat of her late '
                                'brother, Sen. Lindsey Graham; her first elected office. Won the '
                                'Aug. 25 special Republican primary runoff.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Darline_Graham',
                  'financeNote': 'Committee registered August 2026; its first FEC report is due '
                                 'Oct. 15, 2026.',
                  'campaignSiteUrl': 'https://www.darlinegraham.com/#record',
                  'facts': [{'label': 'Profession', 'value': 'Public administrator'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True}]},
 {'id': 'fl-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Florida',
  'stateCode': 'FL',
  'electionDate': '2026-11-03',
  'seatNote': "Special election for the rest of Marco Rubio's term, through January 2029. Sen. "
              'Ashley Moody (R) was appointed in January 2025.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_special_election_in_Florida',
  'candidates': [{'name': 'Angie Nixon',
                  'party': 'Democratic',
                  'fecId': 'S6FL00830',
                  'committees': ['C00915041'],
                  'currentOffice': 'Florida State Representative',
                  'stateProfile': None,
                  'background': 'Florida state representative from Jacksonville since 2020; won '
                                'the August 18 Democratic primary over Alex Vindman.',
                  'backgroundSourceUrl': 'https://en.wikipedia.org/wiki/Angie_Nixon',
                  'facts': [{'label': 'Born', 'value': 'Jacksonville, Florida'},
                            {'label': "Bachelor's", 'value': 'University of Florida'}],
                  'incumbent': False},
                 {'name': 'Ashley Moody',
                  'party': 'Republican',
                  'fecId': 'S6FL00640',
                  'committees': ['C00895763'],
                  'currentOffice': 'U.S. Senator, Florida (appointed)',
                  'stateProfile': None,
                  'background': 'Appointed to the Senate in January 2025; Florida attorney general '
                                '(2019-2025); previously a circuit court judge.',
                  'backgroundSourceUrl': 'https://en.wikipedia.org/wiki/Ashley_Moody',
                  'facts': [{'label': 'Born', 'value': 'Plant City, Florida'},
                            {'label': 'Education',
                             'value': 'B.S., M.S., J.D., University of Florida; LL.M., Stetson'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True}]},
 {'id': 'ia-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Iowa',
  'stateCode': 'IA',
  'electionDate': '2026-11-03',
  'seatNote': 'Open seat: Sen. Joni Ernst (R) is not seeking a third term.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Iowa',
  'candidates': [{'name': 'Josh Turek',
                  'party': 'Democratic',
                  'fecId': 'S6IA00298',
                  'committees': ['C00915645'],
                  'currentOffice': 'Iowa State Representative',
                  'stateProfile': None,
                  'background': 'Iowa state representative from Council Bluffs, first elected in '
                                '2022; two-time Paralympic gold medalist in wheelchair basketball.',
                  'backgroundSourceUrl': 'https://iowacapitaldispatch.com/2026/06/02/rep-josh-turek-wins-u-s-senate-primary-race-against-sen-zach-wahls-ap-projects/',
                  'facts': [{'label': 'Hometown', 'value': 'Council Bluffs, Iowa'}],
                  'incumbent': False},
                 {'name': 'Ashley Hinson',
                  'party': 'Republican',
                  'fecId': 'S6IA00314',
                  'committees': ['C00706267'],
                  'currentOffice': 'U.S. Representative, IA-02',
                  'stateProfile': None,
                  'background': 'U.S. representative since 2021; former Iowa state representative '
                                'and KCRG-TV reporter in Cedar Rapids.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Ashley_Hinson',
                  'facts': [{'label': 'Born', 'value': 'Des Moines, Iowa'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': False}]},
 {'id': 'la-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Louisiana',
  'stateCode': 'LA',
  'electionDate': '2026-11-03',
  'seatNote': 'Open seat: Sen. Bill Cassidy (R) finished third in the May 16 closed Republican '
              'primary.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Louisiana',
  'candidates': [{'name': 'Jamie Davis',
                  'party': 'Democratic',
                  'fecId': 'S6LA00615',
                  'committees': ['C00929117'],
                  'currentOffice': 'Former Tensas Parish Police Juror',
                  'stateProfile': None,
                  'background': 'Farmer from Waterproof, Louisiana; former Tensas Parish police '
                                'juror; member of the Louisiana Democratic State Central '
                                'Committee.',
                  'backgroundSourceUrl': 'https://lailluminator.com/2026/04/30/davis-senate/',
                  'facts': [{'label': 'Hometown', 'value': 'Waterproof, Louisiana'},
                            {'label': 'Profession', 'value': 'Farmer'}],
                  'incumbent': False},
                 {'name': 'Julia Letlow',
                  'party': 'Republican',
                  'fecId': 'S6LA00664',
                  'committees': ['C00935411'],
                  'currentOffice': 'U.S. Representative, LA-05',
                  'stateProfile': None,
                  'background': 'U.S. representative since 2021; won the Republican nomination in '
                                'a June 27 runoff.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Julia_Letlow',
                  'facts': [{'label': 'Born', 'value': 'Monroe, Louisiana'},
                            {'label': 'Education',
                             'value': 'B.A. & M.A., Univ. of Louisiana Monroe; Ph.D., Univ. of '
                                      'South Florida'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': False}]},
 {'id': 'oh-sen-2026',
  'office': 'U.S. Senate',
  'state': 'Ohio',
  'stateCode': 'OH',
  'electionDate': '2026-11-03',
  'seatNote': "Special election for the rest of JD Vance's term, through January 2029. Sen. Jon "
              'Husted (R) was appointed in January 2025.',
  'sourceUrl': 'https://en.wikipedia.org/wiki/2026_United_States_Senate_special_election_in_Ohio',
  'candidates': [{'name': 'Sherrod Brown',
                  'party': 'Democratic',
                  'fecId': 'S6OH00163',
                  'committees': ['C00916288'],
                  'currentOffice': 'Former U.S. Senator, Ohio',
                  'stateProfile': None,
                  'background': 'U.S. senator from Ohio (2007-2025), chair of the Senate Banking '
                                'Committee; U.S. representative (1993-2007); Ohio secretary of '
                                'state (1983-1991).',
                  'backgroundSourceUrl': 'https://en.wikipedia.org/wiki/Sherrod_Brown',
                  'facts': [{'label': 'Born', 'value': 'Mansfield, Ohio'},
                            {'label': 'Education',
                             'value': 'B.A., Yale; M.A. & M.P.A., Ohio State'}],
                  'incumbent': False,
                  'photo': {'url': 'https://unitedstates.github.io/images/congress/225x275/B000944.jpg',
                            'credit': 'U.S. Congress, public domain, via the unitedstates project',
                            'sourceUrl': 'https://github.com/unitedstates/images'}},
                 {'name': 'Jon Husted',
                  'party': 'Republican',
                  'fecId': 'S6OH00304',
                  'committees': ['C00896019', 'C00895276'],
                  'currentOffice': 'U.S. Senator, Ohio (appointed)',
                  'stateProfile': None,
                  'background': 'Appointed to the Senate in January 2025; Ohio lieutenant governor '
                                '(2019-2025) and secretary of state (2011-2019); former Ohio House '
                                'speaker.',
                  'backgroundSourceUrl': 'https://en.wikipedia.org/wiki/Jon_Husted',
                  'facts': [{'label': 'Born', 'value': 'Royal Oak, Michigan'},
                            {'label': 'Education', 'value': 'B.A. & M.A., University of Dayton'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True,
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Sen._Jon_Husted_official_portrait,_119th_Congress_(cropped).jpg?width=240',
                            'credit': 'U.S. Senate (photo by John Shinkle), public domain',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Sen._Jon_Husted_official_portrait,_119th_Congress_(cropped).jpg'}}]},
 {'id': 'fl-13-2026',
  'office': 'U.S. House',
  'title': "U.S. House, Florida's 13th District",
  'label': 'FL-13',
  'state': 'Florida',
  'stateCode': 'FL',
  'electionDate': '2026-11-03',
  'seatNote': 'Rep. Anna Paulina Luna (R) is seeking a third term.',
  'sourceUrl': 'https://www.fox13news.com/news/florida-congressional-race-retired-army-leela-gray-challenges-anna-paulina-luna',
  'candidates': [{'name': 'Leela Gray',
                  'party': 'Democratic',
                  'fecId': 'H6FL13312',
                  'committees': ['C00937441'],
                  'currentOffice': 'Retired U.S. Army Brigadier General',
                  'stateProfile': None,
                  'background': 'Retired Army brigadier general with more than 30 years in '
                                'uniform, retiring in 2018 as deputy commanding general of U.S. '
                                'Army Central; attorney.',
                  'backgroundSourceUrl': 'https://www.newpolitics.org/candidates/leela-gray',
                  'facts': [{'label': 'Profession', 'value': 'Attorney; retired Army officer'}],
                  'incumbent': False,
                  'photo': {'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/2015_Brigadier_General_Leela_Gray_(cropped).jpg?width=240',
                            'credit': 'U.S. Department of Defense, public domain',
                            'sourceUrl': 'https://commons.wikimedia.org/wiki/File:2015_Brigadier_General_Leela_Gray_(cropped).jpg'}},
                 {'name': 'Anna Paulina Luna',
                  'party': 'Republican',
                  'fecId': 'H0FL13158',
                  'committees': [],
                  'currentOffice': 'U.S. Representative, FL-13',
                  'stateProfile': None,
                  'background': "U.S. representative for Florida's 13th district since 2023.",
                  'backgroundSourceUrl': 'https://ballotpedia.org/Anna_Paulina_Luna',
                  'facts': [{'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True,
                  'photo': {'url': 'https://unitedstates.github.io/images/congress/225x275/L000596.jpg',
                            'credit': 'U.S. Congress, public domain, via the unitedstates project',
                            'sourceUrl': 'https://github.com/unitedstates/images'}}]},
 {'id': 'ga-02-2026',
  'office': 'U.S. House',
  'title': "U.S. House, Georgia's 2nd District",
  'label': 'GA-02',
  'state': 'Georgia',
  'stateCode': 'GA',
  'electionDate': '2026-11-03',
  'seatNote': 'Rep. Sanford Bishop (D) is seeking an 18th term.',
  'sourceUrl': 'https://ajc.com/politics/2026/04/us-house-district-2-bishop-avoids-primary-challenge-in-sw-georgia/',
  'candidates': [{'name': 'Sanford Bishop',
                  'party': 'Democratic',
                  'fecId': 'H2GA02031',
                  'committees': ['C00266940'],
                  'currentOffice': 'U.S. Representative, GA-02',
                  'stateProfile': None,
                  'background': 'U.S. representative since 1993; attorney and U.S. Army veteran; '
                                'former Georgia state legislator.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Sanford_Bishop_Jr.',
                  'facts': [{'label': 'Born', 'value': 'Mobile, Alabama'},
                            {'label': 'Education',
                             'value': 'B.A., Morehouse College; J.D., Emory University'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True},
                 {'name': 'Matt Day',
                  'party': 'Republican',
                  'fecId': 'H6GA01182',
                  'committees': [],
                  'currentOffice': 'Business owner',
                  'stateProfile': None,
                  'background': 'Business owner from Douglas, Georgia; founded the staffing '
                                'companies Glaziers on Demand, Glazier Nation, and ChoreNab.',
                  'backgroundSourceUrl': 'https://ajc.com/politics/2026/04/us-house-district-2-bishop-avoids-primary-challenge-in-sw-georgia/',
                  'facts': [{'label': 'Hometown', 'value': 'Douglas, Georgia'},
                            {'label': 'Profession', 'value': 'Business owner'}],
                  'incumbent': False}]},
 {'id': 'nc-01-2026',
  'office': 'U.S. House',
  'title': "U.S. House, North Carolina's 1st District",
  'label': 'NC-01',
  'state': 'North Carolina',
  'stateCode': 'NC',
  'electionDate': '2026-11-03',
  'seatNote': 'Rematch of 2024. The district was redrawn in 2025 and now leans more Republican.',
  'sourceUrl': 'https://ncnewsline.com/2026/03/03/ager-wraps-up-dem-nomination-in-nc-11-buckhout-takes-nc-01-republican-primary/',
  'candidates': [{'name': 'Don Davis',
                  'party': 'Democratic',
                  'fecId': 'H2NC02287',
                  'committees': [],
                  'currentOffice': 'U.S. Representative, NC-01',
                  'stateProfile': None,
                  'background': 'U.S. representative since 2023; U.S. Air Force veteran; former '
                                'mayor of Snow Hill and North Carolina state senator.',
                  'backgroundSourceUrl': 'https://www.witn.com/2026/03/04/buckhout-wins-primary-setting-up-fall-face-off-with-congressman-don-davis/',
                  'facts': [{'label': 'Hometown', 'value': 'Snow Hill, North Carolina'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True},
                 {'name': 'Laurie Buckhout',
                  'party': 'Republican',
                  'fecId': 'H4NC01137',
                  'committees': [],
                  'currentOffice': 'Retired U.S. Army Colonel',
                  'stateProfile': None,
                  'background': 'Retired Army colonel; Republican nominee for this seat in 2024; '
                                'appointed acting assistant secretary of war for cyber policy.',
                  'backgroundSourceUrl': 'https://www.witn.com/2026/03/04/buckhout-wins-primary-setting-up-fall-face-off-with-congressman-don-davis/',
                  'facts': [{'label': 'Profession', 'value': 'Retired Army officer'}],
                  'incumbent': False}]},
 {'id': 'oh-09-2026',
  'office': 'U.S. House',
  'title': "U.S. House, Ohio's 9th District",
  'label': 'OH-09',
  'state': 'Ohio',
  'stateCode': 'OH',
  'electionDate': '2026-11-03',
  'seatNote': 'Rematch of 2024, which Kaptur won by under one point. The district was redrawn in '
              '2025 and now leans more Republican.',
  'sourceUrl': 'https://news.ballotpedia.org/2026/08/06/redistricting-redraws-ohios-9th-district-ahead-of-2026-kaptur-merrin-rematch/',
  'candidates': [{'name': 'Marcy Kaptur',
                  'party': 'Democratic',
                  'fecId': 'H2OH09031',
                  'committees': [],
                  'currentOffice': 'U.S. Representative, OH-09',
                  'stateProfile': None,
                  'background': 'U.S. representative since 1983, the longest-serving woman in '
                                'congressional history.',
                  'backgroundSourceUrl': 'https://news.ballotpedia.org/2026/08/06/redistricting-redraws-ohios-9th-district-ahead-of-2026-kaptur-merrin-rematch/',
                  'facts': [{'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True},
                 {'name': 'Derek Merrin',
                  'party': 'Republican',
                  'fecId': 'H4OH09169',
                  'committees': [],
                  'currentOffice': 'Former Ohio State Representative',
                  'stateProfile': None,
                  'background': 'Ohio state representative (2016-2024); real estate investor; '
                                'Republican nominee for this seat in 2024.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Derek_Merrin',
                  'facts': [{'label': 'Born', 'value': 'Smithtown, New York'},
                            {'label': 'Profession', 'value': 'Real estate investor'}],
                  'incumbent': False}]},
 {'id': 'oh-13-2026',
  'office': 'U.S. House',
  'title': "U.S. House, Ohio's 13th District",
  'label': 'OH-13',
  'state': 'Ohio',
  'stateCode': 'OH',
  'electionDate': '2026-11-03',
  'seatNote': 'The district was redrawn in 2025 to favor Democrats; 2024 nominee Kevin Coughlin '
              '(R) withdrew afterward.',
  'sourceUrl': 'https://ohiocapitaljournal.com/?p=37409',
  'candidates': [{'name': 'Emilia Sykes',
                  'party': 'Democratic',
                  'fecId': 'H2OH13264',
                  'committees': ['C00801274'],
                  'currentOffice': 'U.S. Representative, OH-13',
                  'stateProfile': None,
                  'background': 'U.S. representative since 2023; former Ohio House minority '
                                'leader.',
                  'backgroundSourceUrl': 'https://ballotpedia.org/Emilia_Sykes',
                  'facts': [{'label': 'Born', 'value': 'Akron, Ohio'},
                            {'label': 'Current office pay', 'value': '$174,000/yr'}],
                  'incumbent': True},
                 {'name': 'Carey Coleman',
                  'party': 'Republican',
                  'fecId': 'H6OH13307',
                  'committees': ['C00933432'],
                  'currentOffice': 'Former radio host',
                  'stateProfile': None,
                  'background': 'Former radio host; won the five-way May 5 Republican primary.',
                  'backgroundSourceUrl': 'https://ohiocapitaljournal.com/?p=37409',
                  'facts': [{'label': 'Profession', 'value': 'Radio host'}],
                  'incumbent': False}]}]


class FECFetcher:
    def __init__(self, key: str):
        self.key = key
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "congress-tracker/1.0"})
        self.failures = 0

    def _get(self, path: str, params: Dict) -> Optional[Dict]:
        time.sleep(REQUEST_DELAY)
        p = dict(params)
        p["api_key"] = self.key
        for attempt in range(3):
            try:
                r = self.s.get(f"{FEC_BASE}{path}", params=p, timeout=(10, 30))
                if r.status_code == 429:
                    time.sleep(20 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    # Never print the URL: it carries the API key.
                    print(f"  [fec] {path} failed: {type(e).__name__}", file=sys.stderr)
                    self.failures += 1
                    return None
                time.sleep(5)
        self.failures += 1
        return None

    def committee_totals(self, committee_id: str) -> Optional[Dict]:
        """Latest totals for one committee, current cycle, falling back one cycle."""
        cycle = current_cycle()
        for c in (cycle, cycle - 2):
            data = self._get(f"/committee/{committee_id}/totals/",
                             {"per_page": 1, "cycle": c, "sort": "-coverage_end_date"})
            results = (data or {}).get("results") or []
            if results and results[0].get("last_cash_on_hand_end_period") is not None:
                return results[0]
        return None


def resolve_committees(fetcher: FECFetcher, fec_id: str) -> List[str]:
    data = fetcher._get(f"/candidate/{fec_id}/committees/",
                        {"designation": ["P", "A"], "cycle": current_cycle(), "per_page": 20})
    ids = [r.get("committee_id") for r in (data or {}).get("results") or [] if r.get("committee_id")]
    print(f"    resolved {len(ids)} committee(s) for {fec_id}: {', '.join(ids) or 'none'}")
    return ids


def fetch_candidate_finance(fetcher: FECFetcher, committee_ids: List[str]) -> Dict[str, Any]:
    """Sum totals across every committee a candidate has authorized."""
    raised = pacs = individuals = cash = 0.0
    cycle = None
    got_any = False
    for cid in committee_ids:
        t = fetcher.committee_totals(cid)
        if not t:
            continue
        got_any = True
        raised += t.get("receipts") or 0
        pacs += (t.get("other_political_committee_contributions") or 0) + \
                (t.get("political_party_committee_contributions") or 0)
        individuals += t.get("individual_contributions") or 0
        cash = max(cash, t.get("last_cash_on_hand_end_period") or 0)
        cycle = cycle or t.get("cycle")
    if not got_any:
        return {"available": False}
    denom = pacs + individuals
    return {
        "available": True,
        "cycle": cycle,
        "totalRaised": round(raised),
        "fromPacs": round(pacs),
        "fromIndividuals": round(individuals),
        "pacPct": round(pacs / denom * 100) if denom else None,
        "individualPct": round(individuals / denom * 100) if denom else None,
        "cashOnHand": round(cash),
        "source": "OpenFEC API",
    }


def fetch_top_pac_donors(fetcher: FECFetcher, committee_ids: List[str]) -> List[Dict[str, Any]]:
    totals: Dict[str, float] = {}
    donor_ids: Dict[str, str] = {}
    for cid in committee_ids:
        params: Dict[str, Any] = {
            "committee_id": cid,
            "two_year_transaction_period": current_cycle(),
            "contributor_type": "committee",
            "per_page": 100,
            "sort": "-contribution_receipt_amount",
        }
        for _ in range(MAX_SCHED_A_PAGES):
            data = fetcher._get("/schedules/schedule_a/", params)
            if data is None:
                break
            results = data.get("results") or []
            for row in results:
                line = (row.get("line_number") or "").strip().upper()
                if line and line not in DONOR_LINES:
                    continue
                name = (row.get("contributor_name") or "").strip()
                amt = row.get("contribution_receipt_amount") or 0
                if name and amt > 0:
                    totals[name] = totals.get(name, 0) + amt
                    if name not in donor_ids and row.get("contributor_id"):
                        donor_ids[name] = row["contributor_id"]
            last = (data.get("pagination") or {}).get("last_indexes") or {}
            if not results or not last:
                break
            params = {**params, **last}
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:TOP_PAC_DONORS]
    out = []
    for name, amt in ranked:
        item: Dict[str, Any] = {"name": name, "amount": round(amt)}
        if name in donor_ids:
            item["committeeId"] = donor_ids[name]
            item["fecUrl"] = f"https://www.fec.gov/data/committee/{donor_ids[name]}/"
        out.append(item)
    return out


def _kind_label(info: Dict[str, Any]) -> str:
    """The FEC's own classification of a committee, in plain words."""
    if (info.get("committee_id") or "").upper() in CONDUIT_COMMITTEE_IDS:
        return CONDUIT_LABEL
    desig = (info.get("designation") or "").upper()
    ctype = (info.get("committee_type") or "").upper()
    orgt = (info.get("organization_type") or "").upper()
    if desig == "J":
        return "joint fundraising"
    if desig == "D":
        return "leadership PAC"
    if desig in ("P", "A"):
        return "candidate committee"
    if ctype in ("X", "Y", "Z"):
        return "party committee"
    if ctype == "O":
        return "super PAC"
    if orgt in ("C", "W"):
        return "corporate PAC"
    if orgt == "L":
        return "labor union PAC"
    if orgt == "T":
        return "trade assoc. PAC"
    if orgt == "M":
        return "membership org PAC"
    if orgt == "V":
        return "co-op PAC"
    return "PAC"


def classify_donor_committees(fetcher: FECFetcher, donors: List[Dict[str, Any]],
                              cache: Dict[str, Optional[str]]) -> None:
    for d in donors:
        cid = d.get("committeeId")
        if not cid:
            continue
        if cid not in cache:
            data = fetcher._get(f"/committee/{cid}/", {})
            results = (data or {}).get("results") or []
            info = dict(results[0]) if results else {}
            if info:
                info.setdefault("committee_id", cid)
                cache[cid] = _kind_label(info)
            else:
                cache[cid] = None
        if cache.get(cid):
            d["kind"] = cache[cid]


def build_race(fetcher: FECFetcher, race: Dict[str, Any],
               kind_cache: Dict[str, Optional[str]]) -> Dict[str, Any]:
    print(f"\n=== {race['id']} ===")
    candidates = []
    for c in race["candidates"]:
        c = dict(c)
        if not c.get("committees") and c.get("fecId"):
            c["committees"] = resolve_committees(fetcher, c["fecId"])
        finance = fetch_candidate_finance(fetcher, c["committees"])
        donors = fetch_top_pac_donors(fetcher, c["committees"])
        classify_donor_committees(fetcher, donors, kind_cache)
        raised = finance.get("totalRaised")
        print(f"  {c['name']}: {'$%d raised' % raised if raised else 'no FEC data'}, "
              f"{len(donors)} named PAC donors, {sum(1 for d in donors if d.get('kind'))} classified")
        candidates.append({
            **c,
            "financeUrl": f"https://www.fec.gov/data/candidate/{c['fecId']}/" if c.get("fecId") else None,
            "finance": finance,
            "topPacDonors": donors,
        })
    return {
        "id": race["id"], "office": race["office"], "state": race["state"],
        "title": race.get("title"), "label": race.get("label"),
        "stateCode": race["stateCode"], "electionDate": race["electionDate"],
        "seatNote": race["seatNote"], "sourceUrl": race["sourceUrl"],
        "candidates": candidates,
    }


def main():
    if not FEC_API_KEY:
        print("ERROR: FEC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)
    fetcher = FECFetcher(FEC_API_KEY)
    kind_cache: Dict[str, Optional[str]] = {}
    built_races = [build_race(fetcher, race, kind_cache) for race in RACES]

    any_finance = any(c["finance"].get("available") for r in built_races for c in r["candidates"])
    print("\n--- Elections data quality ---")
    print(f"  Races built: {len(built_races)}")
    print(f"  Failed FEC requests: {fetcher.failures}")
    if fetcher.failures and not any_finance:
        print("ERROR: no candidate has finance data and requests failed; "
              "refusing to publish an all-empty dataset.", file=sys.stderr)
        sys.exit(1)

    for built in built_races:
        with open(os.path.join(OUT_DIR, f"{built['id']}.json"), "w") as f:
            json.dump(built, f, indent=1)
    index = [{"id": b["id"], "office": b["office"], "state": b["state"], "label": b.get("label"),
              "electionDate": b["electionDate"],
              "candidates": [{"name": c["name"], "party": c["party"]} for c in b["candidates"]]}
             for b in built_races]
    with open(INDEX, "w") as f:
        json.dump({"lastUpdated": datetime.now(timezone.utc).isoformat(), "races": index}, f, indent=1)
    print(f"Wrote {INDEX} + {len(index)} race file(s)")


if __name__ == "__main__":
    main()
