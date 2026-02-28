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
    max_picks = 30

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

        picks.append(
            Pick(
                pick=pick_num,
                team=team_abbr,
                player=player_name,
                pos=pos,
            )
        )

    return picks


def fetch_all_sources() -> List[Dict]:
    """
    For now, only Tankathon, but returns a flat list of dicts
    so the Draft Board page can stay generic.
    """
    out: List[Dict] = []
    try:
        for p in fetch_tankathon_mock():
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
                "Player": f"ERROR from fetch_tankathon_mock: {e}",
                "Pos": "",
                "Source": "Tankathon",
            }
        )
    # small pause just to be polite; kept for future multi-source
    time.sleep(0.5)
    return out
