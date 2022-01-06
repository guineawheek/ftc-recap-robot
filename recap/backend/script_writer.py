import datetime
import random
import statistics
from .data_fetch import FTCEventsClient

INF_RANK = 999
class EventTeam:
    def __init__(self, data):
        self.data = data
        self.scores = []
        self.mentioned = 0
        self.number = data['teamNumber']
        self.nick = data['nameShort']
        self.rookie = data['rookieYear']
        self.rank = INF_RANK
    
    def mention(self, full=False):
        self.mentioned += 1
        if self.mentioned in (2, 4) and not full: 
            return self.nick
        else:
            # we want to space out the numbers for the benefit of the TTS
            return " ".join(str(self.number)) + " " + self.nick
    
    def relevant_scores(self, exclude=(0,)):
        """Returns the 2 highest scoring matches and the lowest match excluding matches in exclude= """
        s = [x for x in sorted(self.scores, reverse=True) if x not in exclude]
        return (s[0], s[1], s[-1])
    
    def __eq__(self, other):
        return isinstance(other, EventTeam) and self.number == other.number

class ScriptWriter:
    """The video script writer."""
    def __init__(self, event_code, client, init_data=True):
        self.event_code: str = event_code
        self.client: FTCEventsClient = client
        self.event = None

        if not init_data:
            return

        # fetch the event info
        data = self.client.fetch("events", eventCode=self.event_code)
        if not data['events']:
            raise ValueError(f"No events exist with the code {self.event_code}")
        event = data['events'][0]
        self.event = event

        # fetch all team data
        self.teams = {}
        page_idx = 1
        while True:
            data = self.client.fetch("teams", eventCode=self.event_code, page=page_idx)
            for team_data in data['teams']:
                self.teams[team_data['teamNumber']] = EventTeam(team_data)

            if page_idx == data['pageTotal']:
                break
            page_idx += 1
        

        # fetch quals match data
        # the hybrid event data is most useful
        matches = self.client.fetch(f"schedule/{self.event_code}/qual/hybrid")
        self.quals = matches['schedule']

        # team number -> team scores

        # top alliance score
        self.top_score = (0, (99999, 99999))
        for match in self.quals:
            red_side = []
            blue_side = []

            # loop through teams to calculate rankings
            for team in match['teams']:
                number = team['teamNumber']
                if team['station'].startswith("Red"):
                    score = match['scoreRedFinal']
                    red_side.append(number)
                else:
                    score = match['scoreBlueFinal']
                    blue_side.append(number)

                if team['surrogate'] or team['noShow']:
                    # we ignore surrogate positions for the team scores list
                    continue
                # add the score to the team scores list
                self.teams[number].scores.append(score)

            # check if we should replace the top score
            if match['scoreRedFinal'] > self.top_score:
                self.top_score = (match['scoreRedFinal'], tuple(red_side))
            if match['scoreBlueFinal'] > self.top_score:
                self.top_score = (match['scoreBlueFinal'], tuple(blue_side))

        # approximate event-specific rankings
        self.team_rankings = sorted(self.teams.keys(), key=lambda t: sum(self.teams[t].scores), reverse=True)
        for rank, number in enumerate(self.team_rankings, 1):
            self.teams[number] = rank

        # TODO: fetch elims data
        self.alliances = self.client.fetch("alliances/" + self.event_code)['alliances']
        # TODO: fetch awards data
        self.awards = self.client.fetch("awards/" + self.event_code)['awards']

    def event_intro(self):
        """Generates an intro sentence for the script."""
        event_name = "Insert Event Name Here"
        event_type = "Insert Event Type Here"
        state_prov = "Insert Event Stateprov Here"
        city = "Insert Event City Here"
        region_name = ""
        date_text = "Never"

        event = self.event
        event_name = event['name']
        event_type = event['typeName']

        state_abbrev = event['stateprov']
        state_prov = us_abbrev_to_state.get(state_abbrev, "bruh")
        city = event['city']

        if event['regionCode'] in region_names:
            region_name = "in the " + region_names.get(event['regionCode'], "Ligma") + " region"

        date_start = self.client.date_parse(event['dateStart']) 
        date_end = self.client.date_parse(event['dateEnd']) 
        date_fstart = datetime.datetime.strftime(date_start, "%B %d")
        date_fend = datetime.datetime.strftime(date_end, "%B %d")

        if date_fstart == date_fend:
            date_text = f"{date_fstart}, {date_start.year}"

        dialog = f"""Hello, my name is Outreach Lead from Team That Wants Inspire and today on F Tee See Recap,
        we will be talking about the {event_name} {event_type}. 
        This event happened out of {city}, {state_prov} {region_name}, on {date_text}. """.replace("\n", "")

        return dialog
    
    def quals_matches(self):

        """Generates a quals summary"""
        # 
        # mention the highest scoring match. 
        # talk about the highest ranked team in the highest scoring match
        #     talk about the 2nd highest score they put up, 
        #     and the lowest score they put up (as a "high" score)
        #
        # then talk about the next highest ranked unmentioned team and their 3 "best" scores
        # 
        # talk about the team with the lowest score standard deviation as the most "consistent" team
        opening_quip = random.choice([
            "This event sure was competitive yet diverse with both veteran teams and new teams.",
        ])

        highest_quals_score: EventTeam = self.top_score[0]
        highest_quals_team1: EventTeam = self.teams[self.top_score[1]]
        highest_quals_team2: EventTeam = self.teams[self.top_score[2]]

        first_team = min(highest_quals_team1, highest_quals_team2, key=lambda t: t.rank)
        first_scores = first_team.relevant_scores(exclude=(highest_quals_score,))
        second_team = min(self.teams, key=lambda t: t.rank if t != first_team else INF_RANK)
        second_scores = second_team.relevant_scores(exclude=(highest_quals_score,))
        consistent_team = min(self.teams, key=lambda t: statistics.stdev(t.scores) if t != first_team and t != second_team else INF_RANK)
        #consistent_scores = first_team.relevant_scores(exclude=(highest_quals_score,))

        quals_script = f"""{opening_quip}
The highest score in qualification matches was an impressive {highest_quals_score} points by 
{highest_quals_team1.mention()} and {highest_quals_team2.mention()}. 
{first_team.mention()} was a incredibly strong team at this event, also putting up scores of 
{first_scores[0]} points, {first_scores[1]} points, and {first_scores[2]} points,
while {second_team.mention()} also put up {second_scores[0]} points, {second_scores[1]} points, and an average of {statistics.mean(second_team.scores)}.
An incredibly consistent team to watch out for was team {consistent_team.mention()} with a high score of {max(consistent_team.scores)} and 
an average of {statistics.mean(consistent_team.scores)}, with not much difference between those two!
"""


    def elims_matches(self):
        """generates an elims script"""
        # read off all four captains
        # mention who the semifinals winners pick
        # read off how both semifinal sets go (whether there is a tiebreaker, the final winning scores)
        # read off how finals goes similar to semifinals
    
    def awards_conclusion(self):
        """awards/conclusion"""
        # read off the inspire nominees
        # say some quip about being excited to see how teams will do later in the season

us_state_to_abbrev = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "District of Columbia": "DC",
    "American Samoa": "AS",
    "Guam": "GU",
    "Northern Mariana Islands": "MP",
    "Puerto Rico": "PR",
    "United States Minor Outlying Islands": "UM",
    "U.S. Virgin Islands": "VI",
}
us_abbrev_to_state = {b:a for a, b in us_state_to_abbrev.items()}

# these are all the us regions that exist
region_names = {
    "USCHS": "Chesapeake",
    "USNYNY": "New York City",
    "USNYEX": "Excelsior",
    "USNYLI": "Long Island",
    "USTXCE": "Central Texas",
    "USTXHO": "Houston",
    "USTXNO": "Northern Texas",
    "USTXSO": "Southern Texas",
    "USTXWP": "Texas Panhandle",
    "USCANO": "Norcal",
    "USCALA": "Socal",
    "USCASD": "San Diego",
}