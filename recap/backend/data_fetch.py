import requests
import base64
import datetime

BASE_API_URL = "https://ftc-api.firstinspires.org/v2.0"
SEASON = 2021
class FTCEventsClient:
    def __init__(self, username, token):
        self.username = username
        self.token = token
        self._b64 = base64.b64encode(f"{self.username}:{self.token}".encode()).decode()
        self.session = requests.Session()

    def fetch(self, path, **params):
        r = self.session.get(f"{BASE_API_URL}/{SEASON}/{path}", headers={"Authorization": "Basic " + self._b64}, params=params)
        r.raise_for_status()
        return r.json()
    
    @classmethod
    def date_parse(cls, date_str):
        return datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")

