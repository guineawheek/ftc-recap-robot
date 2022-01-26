import datetime
import random
import statistics
import re
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
        # the second time a team is mentioned use only their full name
        if self.mentioned == 2 and not full: 
            return self.nick
        else:
            # we want to space out the numbers for the benefit of the TTS
            # this randomly changes out zero for the letter "o" for extra inconsistency
            numbers = list(str(self.number))
            if random.random() < 0.5 or len(numbers) not in (4, 5):
                # spell out all numbers
                numbers = [c if c != '0' else random.choice(("0", "o")) for c in str(self.number) ]
                return " ".join(numbers) + " " + self.nick
            else:
                if len(numbers) == 4:
                    # as in "forty forty-two"
                    return f"{numbers[0]}{numbers[1]} {numbers[2]}{numbers[3]} " + self.nick
                else:
                    # as in "sixteen three two six"
                    return f"{numbers[0]}{numbers[1]} {' '.join(numbers[2:])} " + self.nick
    
    def relevant_scores(self, exclude=(0,)):
        """Returns the 2 highest scoring matches and the lowest match excluding matches in exclude= """
        s = [x for x in sorted(self.scores, reverse=True) if x not in exclude]
        return (s[0], s[1], s[-1])
    
    def __eq__(self, other):
        return isinstance(other, EventTeam) and self.number == other.number
    
    def __str__(self):
        return self.mention()

class EventAlliance:
    def __init__(self, data, teams):
        self.data = data
        self.teams = [teams[self.data[z]] for z in ("captain", "round1", "round2", "round3") if self.data[z]]
        self.seed = data['number']
        self.scores = []
    def name(self):
        return get_nth(self.seed) + " alliance"
    def __str__(self):
        return self.name()

class EventElimsSeries:
    def __init__(self, data, series, red_alliance, blue_alliance):
        self.data = data
        self.series = series
        self.winner = "red"
        self.num_rounds = 0 
        self.red_alliance = red_alliance
        self.blue_alliance = blue_alliance
        self.red_scores = []
        self.blue_scores = []

        for match in data:
            if match['series'] != self.series:
                continue
            red, blue = match['scoreRedFinal'], match['scoreBlueFinal']
            self.red_alliance.scores.append(red)
            self.blue_alliance.scores.append(blue)
            self.red_scores.append(red)
            self.blue_scores.append(blue)
            # update the number of rounds
            if match['matchNumber'] > self.num_rounds:
                self.num_rounds = match['matchNumber']
                self.winner = "red" if red > blue else "blue"
            
    def winning_alliance(self):
        return self.red_alliance if self.winner == "red" else self.blue_alliance

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

        rankings = self.client.fetch(f"rankings/{self.event_code}")
        self.rankings = sorted([(x['rank'], self.teams[x['teamNumber']], x['sortOrder1']) for x in rankings['Rankings']], key=lambda x: int(x[0]))

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
            if match['scoreRedFinal'] > self.top_score[0]:
                self.top_score = (match['scoreRedFinal'], tuple(red_side))
            if match['scoreBlueFinal'] > self.top_score[0]:
                self.top_score = (match['scoreBlueFinal'], tuple(blue_side))

        # approximate event-specific rankings
        self.team_rankings = sorted(self.teams.keys(), key=lambda t: sum(self.teams[t].scores), reverse=True)
        for rank, number in enumerate(self.team_rankings, 1):
            self.teams[number].rank = rank

        # fetch alliances and awards
        self.alliances = [EventAlliance(data, self.teams) for data in self.client.fetch("alliances/" + self.event_code)['alliances']]
        self.alliances.sort(key=lambda x: x.seed)
        self.playoffs = []
        self.elims = []
        if self.alliances:
            self.playoffs = self.client.fetch(f"schedule/{self.event_code}/playoff/hybrid")['schedule']
            self.elims = [
                EventElimsSeries(self.playoffs, 1, self.alliances[0], self.alliances[3]),
                EventElimsSeries(self.playoffs, 2, self.alliances[1], self.alliances[2]),
            ]
            self.elims.insert(0, EventElimsSeries(self.playoffs, 0, self.elims[0].winning_alliance(), self.elims[1].winning_alliance()))

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
        if event['name'].startswith("CA-Northern "):
            # hack for norcal prefix chopping
            event_name = event['name'][len("CA-Northern "):]
        else:
            event_name = event['name'][3:] # we clip out the first three chars since it's usually a stateprov code
        event_type = "" #event['typeName'] usually redundant

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
        else:
            date_text = f"{date_fend}, {date_start.year}"

        dialog = f"""Hello, this is Outreach Generator version seven point oh one three and today on Automated Eff Tee See Recap
we will be talking about the {event_name} {event_type} that happened out of {city}, {state_prov} {region_name}, on {date_text}. """

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
            "The competition was strong yet diverse with both veteran teams and new teams.",
            "This competition was electrifying to watch.",
            "This competition was critical for top teams on their way to regionals.",
            "Because of pandemic restrictions, this event was smaller than usual, but was even more intense."
        ])
        if len(self.top_score[1]) == 1:
            opening_quip = "Due to the pandemic, this event was conducted remotely."

        analysis_choices = [
            "Their robot's high scores came from their fast rev slides.",
            "Their robot's fast intake, spending only 2 seconds max on collection each cycle, was critical to their success.",
            "Their robot's speedy lift arm made those high scores possible.",
            "Their robot's 20 to 1 drivetrain gave them the edge they needed.",
            "Their robot's aerodynamic pocketing gave them dominating speed.",
            "Their robot's mecanum drivetrain gave them the precision needed to score.",
            "Their robot's six wheel drive gave them the acceleration needed to score.",
            "Their robot's go build a turret made them unmatched on the shared hub."
            "Their driveteam's many hours of practice have paid off.",
        ]
        top_score_teams = [self.teams[x] for x in self.top_score[1]]
        highest_quals_score: EventTeam = self.top_score[0]

        first_team = min(top_score_teams, key=lambda t: t.rank)
        first_scores = first_team.relevant_scores(exclude=(highest_quals_score,))
        second_team = min(self.teams.values(), key=lambda t: t.rank if t != first_team else INF_RANK)
        second_scores = second_team.relevant_scores(exclude=(highest_quals_score,))
        consistent_team = min(self.teams.values(), key=lambda t: statistics.stdev(t.scores) if t != first_team and t != second_team else INF_RANK)
        #consistent_scores = first_team.relevant_scores(exclude=(highest_quals_score,))

        quals_script = f"""
{opening_quip}
The highest score in qualification matches was an impressive {highest_quals_score} points by 
{word_join(top_score_teams, key=str)}.
{first_team} was one of the top teams at this event, putting up scores of 
{first_scores[0]} points, {first_scores[1]} points, and {first_scores[2]} points.
{random.choice(analysis_choices)}
Additionally, {second_team} also put up {second_scores[0]} points, {second_scores[1]} points, and an average of {statistics.mean(second_team.scores):.1f}.
The most consistent team we saw was {consistent_team} with a high score of {max(consistent_team.scores)} and 
an average of {statistics.mean(consistent_team.scores):.1f}. 
"""
        return quals_script


    def elims_matches(self):
        """generates an elims script"""
        # read off all four captains
        # mention who the semifinals winners pick
        # read off how both semifinal sets go (whether there is a tiebreaker, the final winning scores)
        # if tiebreaker:
        #    "alliance N managed to clutch the win after a tiebreaker and a high score of [n]"

        # read off how finals goes similar to semifinals
        # with "the winning alliance scores something something something"

        if self.event['regionCode'] == "USCHS" and not self.alliances:
            script = f"""Due to the state of the pandemic at the time of the event, there were no eliminations matches.
            Instead of winning and finalist alliances, advancement considers team rank.
            The first ranked team was {self.rankings[0][1]} with {self.rankings[0][2]} ranking points.
            The second ranked team was {self.rankings[1][1]} with {self.rankings[1][2]} ranking points.
            The third ranked team was {self.rankings[2][1]} with {self.rankings[2][2]} ranking points.
            The fourth ranked team was {self.rankings[3][1]} with {self.rankings[3][2]} ranking points. """

            return script

        if not self.alliances:
            return ""

        alliances_script = f"""
During alliance selection, 
the first alliance captain {self.alliances[0].teams[0].mention()} selected {word_join(self.alliances[0].teams[1:], key=lambda x: x.mention())}.
The second captain {self.alliances[1].teams[0].mention()} selected {word_join(self.alliances[1].teams[1:], key=lambda x: x.mention())}.
The third captain {self.alliances[2].teams[0].mention()} selected {word_join(self.alliances[2].teams[1:], key=lambda x: x.mention())}.
Finally, the fourth captain {self.alliances[3].teams[0].mention()} selected {word_join(self.alliances[3].teams[1:], key=lambda x: x.mention())}.
These were strategic picks, combining match scouting, pit scouting, and advancement considerations.
        """
        finals, semis1, semis2 = self.elims

        undefeated = 'undefeated' if self.elims[1].num_rounds == 2  else "in a tiebreaker"
        if semis1.winner == "red":
            semis1_msg = f"first alliance beat fourth alliance {undefeated}"
        else:
            semis1_msg = f"fourth alliance beat first alliance in an {undefeated} upset"
        
        
        if semis2.winner == "red":
            semis2_msg = "second alliance beat third alliance"
        else:
            semis2_msg = "third alliance beat second alliance"
        if semis2.num_rounds == 2:
            semis2_msg += " undefeated"
        else :
            semis2_msg += " clutched through a tiebreaker"
        high_alliance = max(self.alliances, key=lambda z: max(z.scores))

        winners = self.elims[0].winning_alliance()
        finals_red = max(self.elims[0].red_scores) 
        finals_blue = max(self.elims[0].blue_scores)

        elims_script = f"""
In semifinals, the {semis1_msg} and {semis2_msg}. 
In finals, the {winners.name()} composed of {word_join(winners.teams, key=lambda x: x.mention(full=True))} would prevail in 
{self.elims[0].num_rounds} matches. 
The finals rounds would have intense high scores of {finals_red} points from {finals.red_alliance.teams[0]}'s {finals.red_alliance} and 
{finals_blue} points from {finals.blue_alliance.teams[0]}'s {finals.blue_alliance}.
The highest score in eliminations was from {high_alliance.name()} with a score of {max(high_alliance.scores)}. 
These were some high level matches at this tournament at this stage of the season, and I'm excited to see how the season progresses. 
"""
        return alliances_script + elims_script
    
    def awards_conclusion(self):
        """awards/conclusion"""

        inspire_teams = [
            self.teams[a['teamNumber']] for a in sorted(filter(lambda x: x['awardId'] == 11, self.awards), key=lambda a: a['series'])
        ]

        if len(inspire_teams) > 1:
            runners_up = f", followed by {word_join(inspire_teams[1:], lambda x: x.mention(full=True))}"

        if len(inspire_teams):
            awards_script = f"""\nAs for awards, the Inspire nominations were {inspire_teams[0].mention(full=True)} winning{runners_up}. \n"""
        else:
            awards_script = ""
        end_script = "I'm excited to cover how these teams will do at regionals, worlds, or Em Tee Eye in future episodes."

        return awards_script + end_script
        # read off the inspire nominees
        # say some quip about being excited to see how teams will do later in the season
    
    def full_script(self):
        """Returns the full script with some basic preprocessing done."""
        return re.sub(' +', ' ',
            (self.event_intro() + self.quals_matches() + 
            self.elims_matches() + self.awards_conclusion()).replace("\n", " "))

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

def get_nth(n):
    if n > 4:
        return str(n) + "th"
    return ["zeroth", "first", "second", "third", "fourth"][n]

def word_join(lst, key=lambda x: x):
    if len(lst) == 1:
        return key(lst[0])
    else:
        return ", ".join([key(i) for i in lst[0:-1]]) + " and " + key(lst[-1])

if __name__ == "__main__":
    import json
    import sys
    with open("token") as f:
        creds = json.load(f)
    c = FTCEventsClient(creds['username'], creds['token'])
    script = ScriptWriter(sys.argv[1], c)
    print(script.full_script())