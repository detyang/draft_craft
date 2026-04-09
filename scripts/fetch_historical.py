"""Build the local SQLite database used by the Streamlit app.

The script fetches historical draft picks and season-level NBA player totals,
then computes a first-pass Draft Pick Score on a 0-100 scale. The app itself
remains offline-safe because it only reads from SQLite at runtime.

Usage:
    python scripts/fetch_historical.py

Optional flags let you point at local draft JSON dumps, write to a different
database path, or skip the season-stat enrichment step.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
from nba_api.stats.endpoints import DraftHistory, LeagueDashPlayerStats

DEFAULT_DB_PATH = Path(__file__).parent.parent / "src" / "data" / "historical.db"
METHODOLOGY_VERSION = "v1_realized_five_year_surplus"

TEAM_MAP = {
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
    "Hawks": "ATL",
    "Celtics": "BOS",
    "Nets": "BKN",
    "Hornets": "CHA",
    "Bulls": "CHI",
    "Cavaliers": "CLE",
    "Mavericks": "DAL",
    "Nuggets": "DEN",
    "Pistons": "DET",
    "Warriors": "GSW",
    "Rockets": "HOU",
    "Pacers": "IND",
    "Clippers": "LAC",
    "Lakers": "LAL",
    "Grizzlies": "MEM",
    "Heat": "MIA",
    "Bucks": "MIL",
    "Timberwolves": "MIN",
    "Pelicans": "NOP",
    "Knicks": "NYK",
    "Thunder": "OKC",
    "Magic": "ORL",
    "76ers": "PHI",
    "Suns": "PHX",
    "Trail Blazers": "POR",
    "Kings": "SAC",
    "Spurs": "SAS",
    "Raptors": "TOR",
    "Jazz": "UTA",
    "Wizards": "WAS",
    "New Jersey Nets": "BKN",
    "Seattle SuperSonics": "OKC",
    "SuperSonics": "OKC",
    "Vancouver Grizzlies": "MEM",
    "New Orleans Hornets": "NOP",
    "Charlotte Bobcats": "CHA",
}

SCORE_WEIGHTS = {
    "gp": 0.15,
    "min": 0.30,
    "pts": 0.20,
    "reb": 0.10,
    "ast": 0.12,
    "stl": 0.08,
    "blk": 0.05,
}


def normalize_team(name: str) -> str:
    return TEAM_MAP.get(name, name)


def parse_optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def season_label(season_start: int) -> str:
    return f"{season_start}-{str((season_start + 1) % 100).zfill(2)}"


def run_with_retries(label: str, func, retries: int = 3, delay_seconds: float = 1.5):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - network behavior is external
            last_error = exc
            print(f"{label}: attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(delay_seconds * attempt)
    raise last_error


def generate_sample_picks(year: int) -> list[dict]:
    """Generate simplified fallback picks when the draft endpoint is unavailable."""
    samples = {
        2003: [
            {
                "personId": 2544,
                "pickNum": 1,
                "roundNum": 1,
                "teamId": {"teamName": "Cleveland Cavaliers", "teamId": 1610612739},
                "playerName": "LeBron James",
                "playerPosition": "F",
                "organization": "St. Vincent-St. Mary High School (Ohio)",
            },
            {
                "personId": 101236,
                "pickNum": 2,
                "roundNum": 1,
                "teamId": {"teamName": "Detroit Pistons", "teamId": 1610612765},
                "playerName": "Darko Milicic",
                "playerPosition": "C",
                "organization": "Hemofarm (Serbia)",
            },
            {
                "personId": 2546,
                "pickNum": 3,
                "roundNum": 1,
                "teamId": {"teamName": "Denver Nuggets", "teamId": 1610612743},
                "playerName": "Carmelo Anthony",
                "playerPosition": "F",
                "organization": "Syracuse University",
            },
        ],
        2023: [
            {
                "personId": 1641705,
                "pickNum": 1,
                "roundNum": 1,
                "teamId": {"teamName": "San Antonio Spurs", "teamId": 1610612759},
                "playerName": "Victor Wembanyama",
                "playerPosition": "C",
                "organization": "Metropolitans 92 (France)",
            },
            {
                "personId": 1641706,
                "pickNum": 2,
                "roundNum": 1,
                "teamId": {"teamName": "Charlotte Hornets", "teamId": 1610612766},
                "playerName": "Brandon Miller",
                "playerPosition": "F",
                "organization": "Alabama",
            },
            {
                "personId": 1630703,
                "pickNum": 3,
                "roundNum": 1,
                "teamId": {"teamName": "Portland Trail Blazers", "teamId": 1610612757},
                "playerName": "Scoot Henderson",
                "playerPosition": "G",
                "organization": "Ignite (G League)",
            },
        ],
    }
    return samples.get(
        year,
        [
            {
                "pickNum": 1,
                "roundNum": 1,
                "teamId": {"teamName": "Atlanta Hawks"},
                "playerName": f"Sample Player {year}",
                "playerPosition": "G",
                "organization": "Sample University",
            },
            {
                "pickNum": 2,
                "roundNum": 1,
                "teamId": {"teamName": "Boston Celtics"},
                "playerName": f"Sample Player {year + 1}",
                "playerPosition": "G",
                "organization": "Sample College",
            },
        ],
    )


def fetch_draft_year(year: int) -> list[dict]:
    """Fetch draft picks for a year using nba_api."""
    draft = DraftHistory(season_year_nullable=year)
    data = draft.get_data_frames()[0]
    picks: list[dict] = []
    for _, row in data.iterrows():
        picks.append(
            {
                "personId": parse_optional_int(row.get("PERSON_ID")),
                "pickNum": parse_optional_int(row.get("OVERALL_PICK")),
                "roundNum": parse_optional_int(row.get("ROUND_NUMBER")) or 1,
                "teamId": {
                    "teamName": row.get("TEAM_NAME", ""),
                    "teamTricode": row.get("TEAM_ABBREVIATION", ""),
                    "teamId": parse_optional_int(row.get("TEAM_ID")),
                },
                "playerName": row.get("PLAYER_NAME", ""),
                "playerPosition": "",
                "organization": row.get("ORGANIZATION", ""),
            }
        )
    return picks


def fetch_season_stats(season_start: int) -> pd.DataFrame:
    """Fetch league-wide player totals for one NBA season."""
    season = season_label(season_start)
    data = LeagueDashPlayerStats(season=season, per_mode_detailed="Totals")
    df = data.get_data_frames()[0]
    if df.empty:
        return pd.DataFrame()

    stats = df[
        [
            "PLAYER_ID",
            "PLAYER_NAME",
            "TEAM_ABBREVIATION",
            "AGE",
            "GP",
            "MIN",
            "PTS",
            "REB",
            "AST",
            "STL",
            "BLK",
            "FGM",
            "FGA",
            "FG_PCT",
            "FG3M",
            "FG3A",
            "FG3_PCT",
            "FTM",
            "FTA",
            "FT_PCT",
            "OREB",
            "DREB",
            "TOV",
            "PF",
        ]
    ].copy()
    stats.columns = [
        "player_id",
        "player",
        "team",
        "age",
        "gp",
        "min",
        "pts",
        "reb",
        "ast",
        "stl",
        "blk",
        "fgm",
        "fga",
        "fg_pct",
        "fg3m",
        "fg3a",
        "fg3_pct",
        "ftm",
        "fta",
        "ft_pct",
        "oreb",
        "dreb",
        "tov",
        "pf",
    ]
    stats["season_start"] = season_start
    stats["season_id"] = season
    return stats


def normalize_pick_record(year: int, raw: dict) -> dict | None:
    pick_num = parse_optional_int(raw.get("pickNum") or raw.get("OVERALL_PICK"))
    if not pick_num:
        return None

    team_obj = raw.get("teamId") or {}
    team_name = team_obj.get("teamName") or raw.get("TEAM_NAME") or ""
    team_abbr = (
        team_obj.get("teamTricode")
        or team_obj.get("teamAbbreviation")
        or raw.get("TEAM_ABBREVIATION")
        or ""
    )
    team = team_abbr or normalize_team(team_name)

    return {
        "year": year,
        "round": parse_optional_int(raw.get("roundNum") or raw.get("ROUND_NUMBER")) or 1,
        "pick": pick_num,
        "player_id": parse_optional_int(
            raw.get("personId") or raw.get("playerId") or raw.get("PERSON_ID")
        ),
        "team_id": parse_optional_int(team_obj.get("teamId") or raw.get("TEAM_ID")),
        "team": team,
        "player": (raw.get("playerName") or raw.get("PLAYER_NAME") or "").strip(),
        "pos": (raw.get("playerPosition") or raw.get("POSITION") or "").strip(),
        "organization": (raw.get("organization") or raw.get("ORGANIZATION") or "").strip(),
    }


def empirical_percentile(sorted_values: np.ndarray, values: np.ndarray) -> np.ndarray:
    if sorted_values.size == 0:
        return np.full(values.shape, 0.5, dtype=float)
    return np.searchsorted(sorted_values, values, side="right") / sorted_values.size


def nearest_expected_value(pick: int, expected_by_pick: dict[int, float], fallback: float) -> float:
    if not expected_by_pick:
        return fallback
    if pick in expected_by_pick:
        return expected_by_pick[pick]
    nearest_pick = min(expected_by_pick.keys(), key=lambda other: abs(other - pick))
    return expected_by_pick[nearest_pick]


def score_band(score: float | None) -> str:
    if score is None or pd.isna(score):
        return "No Score"
    if score >= 80:
        return "Home Run"
    if score >= 65:
        return "Strong Value"
    if score >= 50:
        return "Fair Value"
    if score >= 35:
        return "Weak Value"
    return "Miss"


def compute_pick_scores(picks_df: pd.DataFrame, season_stats_df: pd.DataFrame) -> pd.DataFrame:
    score_columns = [
        "year",
        "round",
        "pick",
        "player_id",
        "team",
        "player",
        "seasons_captured",
        "window_seasons",
        "gp",
        "min",
        "pts",
        "reb",
        "ast",
        "stl",
        "blk",
        "projected_value",
        "expected_value",
        "surplus_value",
        "score",
        "confidence",
        "score_band",
        "methodology_version",
    ]
    eligible_picks = picks_df[picks_df["player_id"].notna()].copy()
    if eligible_picks.empty or season_stats_df.empty:
        return pd.DataFrame(columns=score_columns)

    merged = eligible_picks[
        ["year", "round", "pick", "player_id", "team", "player"]
    ].merge(
        season_stats_df,
        on="player_id",
        how="left",
        suffixes=("", "_season"),
    )
    merged = merged[
        (merged["season_start"] >= merged["year"])
        & (merged["season_start"] <= merged["year"] + 4)
    ]

    grouped = (
        merged.groupby(
            ["year", "round", "pick", "player_id", "team", "player"], as_index=False
        )
        .agg(
            seasons_captured=("season_start", "nunique"),
            gp=("gp", "sum"),
            min=("min", "sum"),
            pts=("pts", "sum"),
            reb=("reb", "sum"),
            ast=("ast", "sum"),
            stl=("stl", "sum"),
            blk=("blk", "sum"),
        )
    )

    result = eligible_picks.merge(
        grouped,
        on=["year", "round", "pick", "player_id", "team", "player"],
        how="left",
    )
    numeric_fill = {
        "seasons_captured": 0,
        "gp": 0.0,
        "min": 0.0,
        "pts": 0.0,
        "reb": 0.0,
        "ast": 0.0,
        "stl": 0.0,
        "blk": 0.0,
    }
    result = result.fillna(numeric_fill)
    result["seasons_captured"] = result["seasons_captured"].astype(int)

    latest_season_start = int(season_stats_df["season_start"].max())
    result["window_seasons"] = (latest_season_start - result["year"] + 1).clip(lower=0, upper=5)

    projection_factor = np.where(result["window_seasons"] > 0, 5.0 / result["window_seasons"], 0.0)
    for metric in SCORE_WEIGHTS:
        result[f"proj_{metric}"] = result[metric] * projection_factor

    for metric, weight in SCORE_WEIGHTS.items():
        complete_metric = result.loc[result["window_seasons"] >= 5, f"proj_{metric}"].to_numpy(dtype=float)
        distribution = np.sort(complete_metric)
        result[f"{metric}_pct"] = empirical_percentile(
            distribution,
            result[f"proj_{metric}"].to_numpy(dtype=float),
        )
        result[f"{metric}_weighted"] = result[f"{metric}_pct"] * weight

    result["projected_value"] = sum(result[f"{metric}_weighted"] for metric in SCORE_WEIGHTS)
    complete = result[result["window_seasons"] >= 5].copy()
    if complete.empty:
        return pd.DataFrame(columns=score_columns)

    expected_by_pick: dict[int, float] = {}
    for pick_num in sorted(complete["pick"].unique()):
        slot_window = result[
            (result["window_seasons"] >= 5)
            & (result["pick"].between(pick_num - 4, pick_num + 4))
        ]
        distances = (slot_window["pick"] - pick_num).abs().to_numpy(dtype=float)
        weights = 1.0 / (1.0 + distances)
        expected_by_pick[pick_num] = float(
            np.average(slot_window["projected_value"].to_numpy(dtype=float), weights=weights)
        )

    fallback_expected = float(complete["projected_value"].mean())
    result["expected_value"] = result["pick"].apply(
        lambda pick_num: nearest_expected_value(int(pick_num), expected_by_pick, fallback_expected)
    )
    result["surplus_value"] = result["projected_value"] - result["expected_value"]

    quality_distribution = np.sort(result.loc[result["window_seasons"] >= 5, "projected_value"].to_numpy(dtype=float))
    surplus_distribution = np.sort(result.loc[result["window_seasons"] >= 5, "surplus_value"].to_numpy(dtype=float))
    result["quality_pct"] = empirical_percentile(
        quality_distribution,
        result["projected_value"].to_numpy(dtype=float),
    )
    result["surplus_pct"] = empirical_percentile(
        surplus_distribution,
        result["surplus_value"].to_numpy(dtype=float),
    )

    result["mature_score"] = 100.0 * (0.45 * result["quality_pct"] + 0.55 * result["surplus_pct"])
    result["confidence"] = (result["window_seasons"] / 5.0) * 100.0
    result["score"] = np.where(
        result["window_seasons"] > 0,
        50.0 + (result["confidence"] / 100.0) * (result["mature_score"] - 50.0),
        np.nan,
    )
    result["score"] = result["score"].clip(lower=0.0, upper=100.0).round(1)
    result["confidence"] = result["confidence"].round(1)
    result["score_band"] = result["score"].apply(score_band)
    result["methodology_version"] = METHODOLOGY_VERSION

    return result[score_columns].sort_values(["year", "pick"], ascending=[True, True]).reset_index(drop=True)


def reset_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS picks;
        DROP TABLE IF EXISTS player_season_stats;
        DROP TABLE IF EXISTS pick_scores;

        CREATE TABLE picks (
            year INTEGER NOT NULL,
            round INTEGER NOT NULL,
            pick INTEGER NOT NULL,
            player_id INTEGER,
            team_id INTEGER,
            team TEXT NOT NULL,
            player TEXT NOT NULL,
            pos TEXT,
            organization TEXT,
            PRIMARY KEY (year, pick)
        );

        CREATE TABLE player_season_stats (
            player_id INTEGER NOT NULL,
            player TEXT NOT NULL,
            season_start INTEGER NOT NULL,
            season_id TEXT NOT NULL,
            team TEXT,
            age REAL,
            gp REAL,
            min REAL,
            pts REAL,
            reb REAL,
            ast REAL,
            stl REAL,
            blk REAL,
            fgm REAL,
            fga REAL,
            fg_pct REAL,
            fg3m REAL,
            fg3a REAL,
            fg3_pct REAL,
            ftm REAL,
            fta REAL,
            ft_pct REAL,
            oreb REAL,
            dreb REAL,
            tov REAL,
            pf REAL,
            PRIMARY KEY (player_id, season_start)
        );

        CREATE TABLE pick_scores (
            year INTEGER NOT NULL,
            round INTEGER NOT NULL,
            pick INTEGER NOT NULL,
            player_id INTEGER,
            team TEXT NOT NULL,
            player TEXT NOT NULL,
            seasons_captured INTEGER NOT NULL,
            window_seasons INTEGER NOT NULL,
            gp REAL NOT NULL,
            min REAL NOT NULL,
            pts REAL NOT NULL,
            reb REAL NOT NULL,
            ast REAL NOT NULL,
            stl REAL NOT NULL,
            blk REAL NOT NULL,
            projected_value REAL,
            expected_value REAL,
            surplus_value REAL,
            score REAL,
            confidence REAL,
            score_band TEXT,
            methodology_version TEXT NOT NULL,
            PRIMARY KEY (year, pick)
        );

        CREATE INDEX idx_picks_team_year ON picks(team, year);
        CREATE INDEX idx_stats_player_season ON player_season_stats(player_id, season_start);
        CREATE INDEX idx_scores_team_year ON pick_scores(team, year);
        """
    )


def write_database(
    db_path: Path,
    picks_df: pd.DataFrame,
    season_stats_df: pd.DataFrame,
    scores_df: pd.DataFrame,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        reset_schema(conn)
        picks_df.to_sql("picks", conn, if_exists="append", index=False)
        if not season_stats_df.empty:
            season_stats_df.to_sql("player_season_stats", conn, if_exists="append", index=False)
        if not scores_df.empty:
            scores_df.to_sql("pick_scores", conn, if_exists="append", index=False)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch historical NBA draft picks, season totals, and a 0-100 draft pick score "
            "into SQLite."
        )
    )
    parser.add_argument(
        "--local-dir",
        help="directory containing '{year}.json' files downloaded previously",
    )
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="generate sample draft data without attempting the draft API",
    )
    parser.add_argument(
        "--skip-season-stats",
        action="store_true",
        help="only populate the picks table; do not fetch season totals or scores",
    )
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="output SQLite path",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    all_picks: list[dict] = []
    draft_network_failed = False

    for year in range(args.start_year, args.end_year + 1):
        raw_picks: list[dict] = []
        try:
            if args.local_dir:
                file_path = Path(args.local_dir) / f"{year}.json"
                if not file_path.exists():
                    print(f"no local file for {year}")
                    continue
                with open(file_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                raw_picks = data.get("picks", []) if isinstance(data, dict) else data
                print(f"loaded {len(raw_picks)} picks for {year} from {file_path}")
            elif args.sample_only:
                raw_picks = generate_sample_picks(year)
                print(f"generated {len(raw_picks)} sample picks for {year}")
            else:
                raw_picks = run_with_retries(
                    f"draft {year}",
                    lambda: fetch_draft_year(year),
                )
                print(f"{year}: fetched {len(raw_picks)} picks")
        except Exception as exc:
            draft_network_failed = True
            print(f"failed {year}: {exc}")
            if not args.local_dir:
                raw_picks = generate_sample_picks(year)
                print(f"{year}: generated {len(raw_picks)} fallback sample picks")

        for raw_pick in raw_picks:
            record = normalize_pick_record(year, raw_pick)
            if record is not None:
                all_picks.append(record)
        time.sleep(0.5)

    picks_df = pd.DataFrame(all_picks).sort_values(["year", "pick"], ascending=[True, True]).reset_index(drop=True)
    if picks_df.empty:
        raise SystemExit("no draft picks were loaded")

    season_stats_df = pd.DataFrame()
    scores_df = pd.DataFrame()
    can_score = (
        not args.skip_season_stats
        and not args.sample_only
        and picks_df["player_id"].notna().any()
    )
    if can_score:
        season_frames: list[pd.DataFrame] = []
        for year in range(args.start_year, args.end_year + 1):
            try:
                season_df = run_with_retries(
                    f"season {season_label(year)}",
                    lambda: fetch_season_stats(year),
                )
                season_frames.append(season_df)
                print(f"{season_label(year)}: fetched {len(season_df)} player rows")
            except Exception as exc:
                print(f"failed season {season_label(year)}: {exc}")
                if draft_network_failed:
                    print("season stat enrichment stopped because network is unavailable")
                    break
                raise
            time.sleep(0.5)

        if season_frames:
            season_stats_df = (
                pd.concat(season_frames, ignore_index=True)
                .drop_duplicates(subset=["player_id", "season_start"])
                .sort_values(["season_start", "player_id"], ascending=[True, True])
                .reset_index(drop=True)
            )
            scores_df = compute_pick_scores(picks_df, season_stats_df)
            print(f"computed scores for {len(scores_df)} picks")
    elif args.sample_only:
        print("skipping season stats and scores because sample data does not represent the full draft class")

    write_database(db_path, picks_df, season_stats_df, scores_df)
    print(f"wrote {len(picks_df)} picks to {db_path}")
    if not season_stats_df.empty:
        print(f"wrote {len(season_stats_df)} player season rows")
    if not scores_df.empty:
        print(f"wrote {len(scores_df)} pick scores using {METHODOLOGY_VERSION}")


if __name__ == "__main__":
    main()
