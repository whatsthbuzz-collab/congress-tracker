#!/usr/bin/env python3
"""
Fetch congressional data from Congress.gov API
Aggregates: members, bills, votes, and basic info
Outputs: congress_data.json for consumption by React frontend
"""

import requests
import json
from datetime import datetime
from typing import List, Dict, Any
import time

# Congress.gov API base URL (no key required for basic use)
API_BASE = "https://api.congress.gov/v3"

# Rate limiting: Congress.gov asks for ~1 second between requests
REQUEST_DELAY = 0.5


class CongressDataFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Congress-Tracker-Bot/1.0"})
        self.all_data = {
            "lastUpdated": datetime.now().isoformat(),
            "members": [],
            "metadata": {
                "dataSource": "Congress.gov API",
                "sourceUrl": "https://api.congress.gov",
                "billsApiUrl": "https://api.congress.gov/v3/bill",
                "membersApiUrl": "https://api.congress.gov/v3/member",
                "votesApiUrl": "https://api.congress.gov/v3/amendment",
            }
        }

    def _request(self, endpoint: str) -> Dict[str, Any]:
        """Make API request with rate limiting"""
        time.sleep(REQUEST_DELAY)
        url = f"{API_BASE}{endpoint}"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return {}

    def fetch_members(self, congress_number: int = 118) -> List[Dict[str, Any]]:
        """
        Fetch all current members of Congress (House + Senate)
        Congress 118 is current as of 2024
        """
        print(f"Fetching members for Congress {congress_number}...")
        
        members = []
        
        # Fetch House members
        offset = 0
        while True:
            endpoint = f"/member?currentMember=true&limit=250&offset={offset}"
            data = self._request(endpoint)
            
            if not data.get("members"):
                break
            
            for member in data["members"]:
                members.append(self._parse_member(member))
            
            # Check if there are more results
            pagination = data.get("pagination", {})
            if pagination.get("count", 0) + offset >= pagination.get("totalCount", 0):
                break
            
            offset += 250
            print(f"  Fetched {len(members)} members so far...")
        
        return members

    def _parse_member(self, member_data: Dict) -> Dict[str, Any]:
        """Parse member data into our format"""
        return {
            "bioguideId": member_data.get("bioguideId"),
            "name": member_data.get("firstName", "") + " " + member_data.get("lastName", ""),
            "firstName": member_data.get("firstName"),
            "lastName": member_data.get("lastName"),
            "party": member_data.get("partyName", "Unknown"),
            "state": member_data.get("state"),
            "chamber": member_data.get("chamber"),  # Senate or House
            "district": member_data.get("district"),  # House only
            "phoneNumber": member_data.get("phone"),
            "website": member_data.get("url"),
            "termStart": member_data.get("termStart"),
            "termEnd": member_data.get("termEnd"),
            "bills": [],
            "votes": [],
            "stockTrades": None,  # Placeholder for future enhancement
            "source": "Congress.gov API",
            "sourceUrl": f"https://www.congress.gov/member/{member_data.get('bioguideId')}"
        }

    def fetch_bills_for_member(self, bioguide_id: str) -> List[Dict[str, Any]]:
        """Fetch bills sponsored/cosponsored by a member"""
        bills = []
        
        # Get bills where member is sponsor
        endpoint = f"/bill?sponsorIdentifier={bioguide_id}&limit=100"
        data = self._request(endpoint)
        
        if data.get("bills"):
            for bill in data["bills"][:20]:  # Limit to 20 most recent for performance
                bills.append(self._parse_bill(bill, "sponsor"))
        
        return bills

    def _parse_bill(self, bill_data: Dict, role: str = "sponsor") -> Dict[str, Any]:
        """Parse bill data"""
        return {
            "billNumber": bill_data.get("number"),
            "title": bill_data.get("title"),
            "summary": bill_data.get("summaries", [{}])[0].get("text", "No summary available"),
            "introducedDate": bill_data.get("introducedDate"),
            "latestAction": bill_data.get("latestAction", {}).get("text", ""),
            "role": role,  # "sponsor" or "cosponsored"
            "source": "Congress.gov API",
            "sourceUrl": f"https://www.congress.gov/bill/{bill_data.get('congress')}/{bill_data.get('type')}/{bill_data.get('number')}"
        }

    def fetch_member_votes(self, bioguide_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch recent votes by a member
        Note: Congress.gov API has limited vote data; full voting records are in House/Senate Clerk data
        """
        votes = []
        
        # This is a simplified approach - full voting records require different endpoints
        # For complete data, would need to scrape House Clerk XML or Senate voting records
        
        return votes

    def aggregate_member_data(self, member: Dict) -> Dict:
        """Fetch all related data for a member"""
        bioguide_id = member.get("bioguideId")
        
        if bioguide_id:
            print(f"  Fetching bills and votes for {member.get('name')}...")
            member["bills"] = self.fetch_bills_for_member(bioguide_id)
            member["votes"] = self.fetch_member_votes(bioguide_id)
        
        return member

    def run(self):
        """Main execution"""
        print("Starting congressional data fetch...")
        
        # Fetch all members
        members = self.fetch_members()
        print(f"Fetched {len(members)} total members")
        
        # Augment with bills and votes for each member
        print("\nFetching bills and votes for each member...")
        for i, member in enumerate(members):
            self.aggregate_member_data(member)
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{len(members)}")
        
        self.all_data["members"] = members
        self.all_data["totalMembers"] = len(members)
        
        return self.all_data

    def save_to_file(self, filename: str = "congress_data.json"):
        """Save fetched data to JSON file"""
        data = self.run()
        
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"\nData saved to {filename}")
        print(f"Total members: {len(data['members'])}")
        print(f"Last updated: {data['lastUpdated']}")
        
        return filename


def main():
    fetcher = CongressDataFetcher()
    fetcher.save_to_file("congress_data.json")


if __name__ == "__main__":
    main()
