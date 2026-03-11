# src/data/historical_drafts.py

from typing import List
from dataclasses import dataclass


@dataclass
class HistoricalPick:
    year: int
    round: int
    pick: int
    team: str
    player: str
    pos: str
    organization: str

def fetch_historical_drafts() -> List[HistoricalPick]:
    """Load historical NBA draft picks from the local SQLite database.

    The database is expected at ``src/data/historical.db``.  It is not created
    by the application itself; instead you should run
    ``python scripts/fetch_historical.py`` on a machine with internet access
    and then copy the resulting database file into this workspace.  This
    avoids repeated network calls at runtime and keeps the Streamlit app
    offline-safe.

    If the database is missing, an empty list is returned and a warning is
    printed.
    """
    from pathlib import Path
    import sqlite3

    # database lives next to this module
    db_path = Path(__file__).parent / "historical.db"
    picks: List[HistoricalPick] = []

    if not db_path.exists():
        print(f"historical database not found at {db_path}; run scripts/fetch_historical.py")
        return picks

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT year, round, pick, team, player, pos, organization FROM picks")
        for year, rnd, pick_num, team, player, pos, organization in cur.fetchall():
            picks.append(HistoricalPick(
                year=year,
                round=rnd,
                pick=pick_num,
                team=team,
                player=player,
                pos=pos,
                organization=organization,
            ))
        conn.close()
        print(f"Loaded {len(picks)} picks from database {db_path}")
    except Exception as e:
        print(f"Failed to read historical database: {e}")
    return picks

def normalize_team_name(team_name: str) -> str:
    """Convert full team name to abbreviation"""
    # Mapping from data.nba.net team names to abbreviations
    mappings = {
        'Atlanta Hawks': 'ATL',
        'Boston Celtics': 'BOS',
        'Brooklyn Nets': 'BKN',
        'Charlotte Hornets': 'CHA',
        'Chicago Bulls': 'CHI',
        'Cleveland Cavaliers': 'CLE',
        'Dallas Mavericks': 'DAL',
        'Denver Nuggets': 'DEN',
        'Detroit Pistons': 'DET',
        'Golden State Warriors': 'GSW',
        'Houston Rockets': 'HOU',
        'Indiana Pacers': 'IND',
        'LA Clippers': 'LAC',
        'Los Angeles Lakers': 'LAL',
        'Memphis Grizzlies': 'MEM',
        'Miami Heat': 'MIA',
        'Milwaukee Bucks': 'MIL',
        'Minnesota Timberwolves': 'MIN',
        'New Orleans Pelicans': 'NOP',
        'New York Knicks': 'NYK',
        'Oklahoma City Thunder': 'OKC',
        'Orlando Magic': 'ORL',
        'Philadelphia 76ers': 'PHI',
        'Phoenix Suns': 'PHX',
        'Portland Trail Blazers': 'POR',
        'Sacramento Kings': 'SAC',
        'San Antonio Spurs': 'SAS',
        'Toronto Raptors': 'TOR',
        'Utah Jazz': 'UTA',
        'Washington Wizards': 'WAS',
        # Historical names
        'New Jersey Nets': 'BKN',
        'Seattle SuperSonics': 'OKC',
        'Vancouver Grizzlies': 'MEM',
        'New Orleans Hornets': 'NOP',
        'Charlotte Bobcats': 'CHA',
    }
    return mappings.get(team_name, team_name)

# Cache the data
HISTORICAL_DRAFTS = fetch_historical_drafts()

def get_historical_picks_for_team(team: str) -> List[HistoricalPick]:
    """Get historical draft picks for a specific team from 2000 onwards."""
    return [pick for pick in HISTORICAL_DRAFTS if pick.team == team and pick.year >= 2000]