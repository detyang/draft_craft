# src/data/mock_sources.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict
import re
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DraftCraftBot/1.0; +https://github.com/detyang/draft_craft)"
    )
}

TEAM_ABBREV_ALIASES = {
    "gs": "GSW",
    "no": "NOP",
    "ny": "NYK",
    "sa": "SAS",
    "atlanta": "ATL",
    "boston": "BOS",
    "brooklyn": "BKN",
    "charlotte": "CHA",
    "chicago": "CHI",
    "cleveland": "CLE",
    "dallas": "DAL",
    "denver": "DEN",
    "detroit": "DET",
    "golden st": "GSW",
    "golden state": "GSW",
    "houston": "HOU",
    "indiana": "IND",
    "la clippers": "LAC",
    "los angeles clippers": "LAC",
    "la lakers": "LAL",
    "los angeles lakers": "LAL",
    "memphis": "MEM",
    "miami": "MIA",
    "milwaukee": "MIL",
    "minnesota": "MIN",
    "new orleans": "NOP",
    "new york": "NYK",
    "oklahoma cty": "OKC",
    "oklahoma city": "OKC",
    "orlando": "ORL",
    "philadelphia": "PHI",
    "phoenix": "PHX",
    "portland": "POR",
    "sacramento": "SAC",
    "san antonio": "SAS",
    "toronto": "TOR",
    "utah": "UTA",
    "washington": "WAS",
}

KNOWN_TEAM_ABBREVS = set(TEAM_ABBREV_ALIASES.values())


@dataclass
class Pick:
    pick: int
    team: str
    player: str
    pos: str
    source: str = "Tankathon"


def _get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def _normalize_team(team: str) -> str:
    team = team.strip()
    if not team:
        return ""

    # Already an abbreviation (Tankathon format).
    upper = team.upper()
    if upper in KNOWN_TEAM_ABBREVS:
        return upper

    # Normalize full-name aliases from other sources.
    normalized = re.sub(r"[^a-z0-9 ]+", " ", team.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return TEAM_ABBREV_ALIASES.get(normalized, team)


def fetch_tankathon_mock() -> List[Pick]:
    """
    Scrape Tankathon NBA Mock Draft (Round 1) and return a list of Picks.

    Parse explicit row elements instead of page-wide text to keep fields aligned:
      - pick: .mock-row-pick-number
      - team: .mock-row-logo img[alt]
      - player: .mock-row-name
      - pos: left side of .mock-row-school-position (before " | ")
    """
    url = "https://www.tankathon.com/mock_draft"
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    picks: List[Pick] = []
    max_picks = 60

    for row in soup.select(".mock-row"):
        if len(picks) >= max_picks:
            break

        pick_el = row.select_one(".mock-row-pick-number")
        player_el = row.select_one(".mock-row-name a, .mock-row-name")
        school_pos_el = row.select_one(".mock-row-school-position")
        team_img_el = row.select_one(".mock-row-logo img")

        if not pick_el or not player_el:
            continue

        pick_txt = pick_el.get_text(strip=True)
        if not re.fullmatch(r"\d{1,2}", pick_txt):
            continue
        pick_num = int(pick_txt)
        if pick_num > max_picks:
            continue

        player_name = player_el.get_text(" ", strip=True)
        school_pos_txt = school_pos_el.get_text(" ", strip=True) if school_pos_el else ""
        pos = school_pos_txt.split(" | ", 1)[0].strip() if school_pos_txt else ""

        team_abbr = ""
        if team_img_el:
            team_abbr = (team_img_el.get("alt") or "").strip()
            if not team_abbr:
                team_abbr = (team_img_el.get("title") or "").strip()
        team_abbr = _normalize_team(team_abbr)

        picks.append(
            Pick(
                pick=pick_num,
                team=team_abbr,
                player=player_name,
                pos=pos,
            )
        )

    return picks


def fetch_nbadraftnet_mock() -> List[Pick]:
    """
    Scrape NBADraft.net mock draft (Round 1) and return a list of Picks.

    We parse the first table with columns:
      # | Team | Player | ... | P | ...
    and map:
      - pick -> '#'
      - team -> 'Team' (strip leading '*' markers)
      - player -> 'Player'
      - pos -> 'P'
    """
    url = "https://www.nbadraft.net/nba-mock-drafts/"
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    picks_by_number: Dict[int, Pick] = {}
    max_picks = 60

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        headers = [th.get_text(" ", strip=True) for th in rows[0].find_all(["th", "td"])]
        if not headers:
            continue

        header_index = {h: i for i, h in enumerate(headers)}
        if not {"#", "Team", "Player", "P"}.issubset(header_index.keys()):
            continue

        pick_i = header_index["#"]
        team_i = header_index["Team"]
        player_i = header_index["Player"]
        pos_i = header_index["P"]

        for row in rows[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) <= max(pick_i, team_i, player_i, pos_i):
                continue

            pick_txt = cells[pick_i]
            if not re.fullmatch(r"\d{1,2}", pick_txt):
                continue
            pick_num = int(pick_txt)
            if pick_num > max_picks:
                continue
            if pick_num in picks_by_number:
                continue

            team = re.sub(r"^\*+", "", cells[team_i]).strip()
            team = _normalize_team(team)
            player = cells[player_i].strip()
            pos = cells[pos_i].strip()
            if not player:
                continue

            picks_by_number[pick_num] = Pick(
                pick=pick_num,
                team=team,
                player=player,
                pos=pos,
                source="NBADraft.net",
            )

            if len(picks_by_number) >= max_picks:
                break

        if len(picks_by_number) >= max_picks:
            break

    picks = [picks_by_number[n] for n in sorted(picks_by_number.keys())]
    return picks


def fetch_all_sources() -> List[Dict]:
    """
    Fetch all supported mock draft sources and return a flat list of dicts.
    """
    out: List[Dict] = []

    source_fetchers = [
        ("Tankathon", fetch_tankathon_mock),
        ("NBADraft.net", fetch_nbadraftnet_mock),
    ]

    for source_name, fetcher in source_fetchers:
        try:
            for p in fetcher():
                out.append(
                    {
                        "Pick": p.pick,
                        "Team": p.team,
                        "Player": p.player,
                        "Pos": p.pos,
                        "Source": p.source,
                    }
                )
        except Exception as e:
            out.append(
                {
                    "Pick": None,
                    "Team": "",
                    "Player": f"ERROR from {fetcher.__name__}: {e}",
                    "Pos": "",
                    "Source": source_name,
                }
            )

        # small pause between sources to be polite
        time.sleep(0.5)

    return out
