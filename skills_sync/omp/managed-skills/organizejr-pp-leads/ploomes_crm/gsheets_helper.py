import json
import jwt
import time
import requests
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

class SheetData:
    def __init__(self, values):
        self.values = values
        self.max_col = max((len(r) for r in values), default=0)
        for r in self.values:
            r.extend([""] * (self.max_col - len(r)))
        self.max_row = len(self.values)
    
    def cell_value(self, row_idx, col):
        if row_idx <= len(self.values):
            row = self.values[row_idx - 1]
            if col <= len(row):
                return row[col - 1]
        return ""
    
    def set_cell(self, row_idx, col, value):
        while len(self.values) < row_idx:
            self.values.append([""] * self.max_col)
        while len(self.values[row_idx - 1]) < col:
            self.values[row_idx - 1].append("")
            self.max_col = max(self.max_col, col)
        self.values[row_idx - 1][col - 1] = value

def get_sheets_service():
    creds_path = "/home/lucas/.config/gcloud/legacy_credentials/gemini-cli-sa@probable-life-428216-k8.iam.gserviceaccount.com/adc.json"
    with open(creds_path) as f: creds_json = json.load(f)
    now = int(time.time())
    claims = {"iss": creds_json["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets", "aud": creds_json["token_uri"], "exp": now + 3600, "iat": now}
    token = jwt.encode(claims, creds_json["private_key"], algorithm="RS256")
    res = requests.post(creds_json["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": token})
    access_token = res.json().get("access_token")
    return build('sheets', 'v4', credentials=Credentials(access_token))