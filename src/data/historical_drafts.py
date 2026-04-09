# src/data/historical_drafts.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class HistoricalPick:
    year: int
    round: int
    pick: int
    team: str
    player: str
    pos: str
    organization: str
    player_id: int | None = None
    draft_pick_score: float | None = None
    score_confidence: float | None = None
    score_band: str | None = None


def _table_exists(cur, table_name: str) -> bool:
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def fetch_historical_drafts() -> List[HistoricalPick]:
    """Load historical NBA draft picks from the local SQLite database.

    The database is expected at ``src/data/historical.db``. It is not created
    by the application itself; instead run ``python scripts/fetch_historical.py``
    on a machine with NBA API access and then use the resulting database file
    in the app environment.

    If the database is missing, an empty list is returned and a warning is
    printed.
    """
    from pathlib import Path
    import sqlite3

    db_path = Path(__file__).parent / "historical.db"
    picks: List[HistoricalPick] = []

    if not db_path.exists():
        print(f"historical database not found at {db_path}; run scripts/fetch_historical.py")
        return picks

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        pick_columns = {
            row[1]
            for row in cur.execute("PRAGMA table_info(picks)").fetchall()
        }
        has_player_id = "player_id" in pick_columns
        has_pick_scores = _table_exists(cur, "pick_scores")

        select_columns = [
            "p.year",
            "p.round",
            "p.pick",
            "p.team",
            "p.player",
            "p.pos",
            "p.organization",
        ]
        if has_player_id:
            select_columns.append("p.player_id")
        else:
            select_columns.append("NULL AS player_id")

        if has_pick_scores:
            select_columns.extend(
                [
                    "s.score AS draft_pick_score",
                    "s.confidence AS score_confidence",
                    "s.score_band AS score_band",
                ]
            )
            query = f"""
                SELECT {", ".join(select_columns)}
                FROM picks p
                LEFT JOIN pick_scores s
                    ON p.year = s.year AND p.pick = s.pick
            """
        else:
            select_columns.extend(
                [
                    "NULL AS draft_pick_score",
                    "NULL AS score_confidence",
                    "NULL AS score_band",
                ]
            )
            query = f"SELECT {', '.join(select_columns)} FROM picks p"

        for row in cur.execute(query).fetchall():
            (
                year,
                rnd,
                pick_num,
                team,
                player,
                pos,
                organization,
                player_id,
                draft_pick_score,
                score_confidence,
                score_band,
            ) = row
            picks.append(
                HistoricalPick(
                    year=year,
                    round=rnd,
                    pick=pick_num,
                    team=team,
                    player=player,
                    pos=pos,
                    organization=organization,
                    player_id=player_id,
                    draft_pick_score=draft_pick_score,
                    score_confidence=score_confidence,
                    score_band=score_band,
                )
            )

        conn.close()
        print(f"Loaded {len(picks)} picks from database {db_path}")
    except Exception as exc:
        print(f"Failed to read historical database: {exc}")
    return picks


def normalize_team_name(team_name: str) -> str:
    """Convert full team name to abbreviation."""
    mappings = {
        "Atlanta Hawks": "ATL",
        "Boston Celtics": "BOS",
        "Brooklyn Nets": "BKN",
        "Charlotte Hornets": "CHA",
        "Chicago Bulls": "CHI",
        "Cleveland Cavaliers": "CLE",
        "Dallas Mavericks": "DAL",
        "Denver Nuggets": "DEN",
        "Detroit Pistons": "DET",
        "Golden State Warriors": "GSW",
        "Houston Rockets": "HOU",
        "Indiana Pacers": "IND",
        "LA Clippers": "LAC",
        "Los Angeles Lakers": "LAL",
        "Memphis Grizzlies": "MEM",
        "Miami Heat": "MIA",
        "Milwaukee Bucks": "MIL",
        "Minnesota Timberwolves": "MIN",
        "New Orleans Pelicans": "NOP",
        "New York Knicks": "NYK",
        "Oklahoma City Thunder": "OKC",
        "Orlando Magic": "ORL",
        "Philadelphia 76ers": "PHI",
        "Phoenix Suns": "PHX",
        "Portland Trail Blazers": "POR",
        "Sacramento Kings": "SAC",
        "San Antonio Spurs": "SAS",
        "Toronto Raptors": "TOR",
        "Utah Jazz": "UTA",
        "Washington Wizards": "WAS",
        "New Jersey Nets": "BKN",
        "Seattle SuperSonics": "OKC",
        "Vancouver Grizzlies": "MEM",
        "New Orleans Hornets": "NOP",
        "Charlotte Bobcats": "CHA",
    }
    return mappings.get(team_name, team_name)


HISTORICAL_DRAFTS = fetch_historical_drafts()


def get_historical_picks_for_team(team: str) -> List[HistoricalPick]:
    """Get historical draft picks for a specific team from 2000 onwards."""
    return [pick for pick in HISTORICAL_DRAFTS if pick.team == team and pick.year >= 2000]


def get_data_last_updated() -> str:
    """Return the local historical database file modification date."""
    from pathlib import Path
    import datetime

    db_path = Path(__file__).parent / "historical.db"
    if not db_path.exists():
        return "unknown"
    ts = db_path.stat().st_mtime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
