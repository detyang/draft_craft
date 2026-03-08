import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
headers = {"User-Agent": "Mozilla/5.0"}
for year in [2023]:
    url = f"https://data.nba.net/prod/v1/{year}/draft.json"
    r = requests.get(url, headers=headers, verify=False)
    print(year, r.status_code)
    print(r.text[:500])
