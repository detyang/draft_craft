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

try:
    from nba_api.stats.endpoints import DraftHistory, LeagueDashPlayerStats, PlayerAwards
except ImportError:  # pragma: no cover - depends on local environment
    DraftHistory = None
    LeagueDashPlayerStats = None
    PlayerAwards = None

DEFAULT_DB_PATH = Path(__file__).parent.parent / "src" / "data" / "historical.db"
DEFAULT_AWARDS_CACHE_PATH = Path(__file__).parent.parent / "src" / "data" / "awards_cache.json"
METHODOLOGY_VERSION = "v2_role_defense_awards_five_year_surplus"
DEFAULT_AWARDS_SAVE_EVERY = 50

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

CORE_METRICS = ("gp", "min", "pts", "reb", "ast", "stl", "blk")

POSITION_SCORE_WEIGHTS = {
    "guard": {
        "gp": 0.14,
        "min": 0.28,
        "pts": 0.24,
        "reb": 0.04,
        "ast": 0.19,
        "stl": 0.07,
        "blk": 0.04,
    },
    "wing": {
        "gp": 0.15,
        "min": 0.28,
        "pts": 0.24,
        "reb": 0.11,
        "ast": 0.10,
        "stl": 0.07,
        "blk": 0.05,
    },
    "big": {
        "gp": 0.15,
        "min": 0.28,
        "pts": 0.21,
        "reb": 0.18,
        "ast": 0.06,
        "stl": 0.03,
        "blk": 0.09,
    },
}

DEFENSE_COMPONENT_WEIGHTS = {
    "guard": {"stl": 0.55, "blk": 0.10, "dreb": 0.35},
    "wing": {"stl": 0.40, "blk": 0.20, "dreb": 0.40},
    "big": {"stl": 0.20, "blk": 0.45, "dreb": 0.35},
}

AWARDS_POINT_VALUES = {
    "roy": 6.0,
    "all_nba_1st": 8.0,
    "all_nba_2nd": 6.0,
    "all_nba_3rd": 4.0,
    "all_star": 2.0,
    "all_star_starter": 1.0,  # bonus on top of All-Star selection
    "mvp": 14.0,
    "dpoy": 11.0,
    "all_def_1st": 4.0,
    "all_def_2nd": 2.5,
}

AWARD_SUMMARY_COLUMNS = [
    "player_id",
    "roy",
    "all_nba_1st",
    "all_nba_2nd",
    "all_nba_3rd",
    "all_star",
    "all_star_starter",
    "mvp",
    "dpoy",
    "all_def_1st",
    "all_def_2nd",
    "awards_points",
    "defense_awards_points",
]


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


def ensure_nba_api_available(feature_label: str) -> None:
    if DraftHistory is not None and LeagueDashPlayerStats is not None and PlayerAwards is not None:
        return
    raise RuntimeError(
        f"{feature_label} requires 'nba_api' to be installed in the active Python environment. "
        "Install with: pip install nba_api (or use your project venv)."
    )


def looks_like_network_unreachable(error: Exception) -> bool:
    text = str(error).lower()
    patterns = (
        "failed to establish a new connection",
        "name or service not known",
        "temporary failure in name resolution",
        "a socket operation was attempted to an unreachable network",
        "max retries exceeded",
        "connection error",
        "timed out",
    )
    return any(pattern in text for pattern in patterns)


def infer_role_bucket(position: str) -> str:
    pos = (position or "").upper().strip()
    if not pos:
        return "wing"

    has_g = "G" in pos
    has_f = "F" in pos
    has_c = "C" in pos

    if has_c and not has_g:
        return "big"
    if has_g and not has_c and not has_f:
        return "guard"
    if has_f and has_c:
        return "big"
    if has_g and has_f:
        return "wing"
    if has_f:
        return "wing"
    if has_g:
        return "guard"
    return "wing"


def metric_weight_for_role(role: str, metric: str) -> float:
    weights = POSITION_SCORE_WEIGHTS.get(role, POSITION_SCORE_WEIGHTS["wing"])
    return float(weights[metric])


def defense_metric_weight_for_role(role: str, metric: str) -> float:
    weights = DEFENSE_COMPONENT_WEIGHTS.get(role, DEFENSE_COMPONENT_WEIGHTS["wing"])
    return float(weights[metric])


def empty_award_summary() -> dict[str, float]:
    return {
        "roy": 0.0,
        "all_nba_1st": 0.0,
        "all_nba_2nd": 0.0,
        "all_nba_3rd": 0.0,
        "all_star": 0.0,
        "all_star_starter": 0.0,
        "mvp": 0.0,
        "dpoy": 0.0,
        "all_def_1st": 0.0,
        "all_def_2nd": 0.0,
        "awards_points": 0.0,
        "defense_awards_points": 0.0,
    }


def summarize_awards_rows(awards_df: pd.DataFrame) -> dict[str, float]:
    summary = empty_award_summary()
    if awards_df.empty:
        return summary

    desc_col = next((c for c in awards_df.columns if c.lower() == "description"), None)
    if not desc_col:
        return summary

    for description in awards_df[desc_col].fillna("").astype(str):
        desc = description.lower().strip()
        if not desc:
            continue

        if "all-star starter" in desc or "all star starter" in desc:
            summary["all_star"] += 1
            summary["all_star_starter"] += 1
            continue
        if "all-star" in desc or "all star" in desc:
            # Exclude ASG MVP from normal All-Star appearance counting.
            if "most valuable player" not in desc:
                summary["all_star"] += 1

        if "rookie of the year" in desc:
            summary["roy"] += 1

        if "most valuable player" in desc and "all-star" not in desc and "all star" not in desc:
            summary["mvp"] += 1

        if "defensive player of the year" in desc:
            summary["dpoy"] += 1

        if ("all-nba" in desc or "all nba" in desc) and "team" in desc:
            if "first team" in desc or "1st team" in desc:
                summary["all_nba_1st"] += 1
            elif "second team" in desc or "2nd team" in desc:
                summary["all_nba_2nd"] += 1
            elif "third team" in desc or "3rd team" in desc:
                summary["all_nba_3rd"] += 1

        if ("all-defensive" in desc or "all defensive" in desc) and "team" in desc:
            if "first team" in desc or "1st team" in desc:
                summary["all_def_1st"] += 1
            elif "second team" in desc or "2nd team" in desc:
                summary["all_def_2nd"] += 1

    summary["awards_points"] = (
        summary["roy"] * AWARDS_POINT_VALUES["roy"]
        + summary["all_nba_1st"] * AWARDS_POINT_VALUES["all_nba_1st"]
        + summary["all_nba_2nd"] * AWARDS_POINT_VALUES["all_nba_2nd"]
        + summary["all_nba_3rd"] * AWARDS_POINT_VALUES["all_nba_3rd"]
        + summary["all_star"] * AWARDS_POINT_VALUES["all_star"]
        + summary["all_star_starter"] * AWARDS_POINT_VALUES["all_star_starter"]
        + summary["mvp"] * AWARDS_POINT_VALUES["mvp"]
        + summary["dpoy"] * AWARDS_POINT_VALUES["dpoy"]
        + summary["all_def_1st"] * AWARDS_POINT_VALUES["all_def_1st"]
        + summary["all_def_2nd"] * AWARDS_POINT_VALUES["all_def_2nd"]
    )
    summary["defense_awards_points"] = (
        summary["dpoy"] * AWARDS_POINT_VALUES["dpoy"]
        + summary["all_def_1st"] * AWARDS_POINT_VALUES["all_def_1st"]
        + summary["all_def_2nd"] * AWARDS_POINT_VALUES["all_def_2nd"]
    )
    return summary


def load_awards_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            return loaded
    except Exception as exc:
        print(f"failed to read awards cache {path}: {exc}")
    return {}


def write_awards_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, sort_keys=True)


def fetch_awards_summaries(
    player_ids: list[int],
    cache_path: Path,
    refresh_cache: bool = False,
    save_every: int = DEFAULT_AWARDS_SAVE_EVERY,
    max_new_lookups: int = 0,
    max_seconds: int = 0,
) -> pd.DataFrame:
    ensure_nba_api_available("Player awards fetch")
    if not player_ids:
        return pd.DataFrame(columns=AWARD_SUMMARY_COLUMNS)

    cache = load_awards_cache(cache_path)
    cache_dirty = False
    rows: list[dict] = []
    unique_player_ids = sorted(set(player_ids))
    total = len(unique_player_ids)
    save_every = max(1, int(save_every))
    max_new_lookups = max(0, int(max_new_lookups))
    max_seconds = max(0, int(max_seconds))
    fetches_since_save = 0
    new_lookups = 0
    awards_network_unavailable = False
    started_at = time.monotonic()
    budget_notice_printed = False
    time_notice_printed = False

    for index, player_id in enumerate(unique_player_ids, start=1):
        key = str(int(player_id))

        if not refresh_cache and key in cache:
            summary = cache[key]
        elif max_new_lookups > 0 and new_lookups >= max_new_lookups:
            summary = empty_award_summary()
        elif max_seconds > 0 and (time.monotonic() - started_at) >= max_seconds:
            summary = empty_award_summary()
        elif awards_network_unavailable:
            summary = empty_award_summary()
        else:
            try:
                awards = run_with_retries(
                    f"awards player {player_id}",
                    lambda: PlayerAwards(player_id=player_id).get_data_frames()[0],
                )
                summary = summarize_awards_rows(awards)
                new_lookups += 1
            except Exception as exc:
                print(f"awards lookup failed for player_id {player_id}: {exc}")
                summary = empty_award_summary()
                if looks_like_network_unreachable(exc):
                    awards_network_unavailable = True
                    print("awards API appears unreachable; using cache/zeros for remaining players")

            cache[key] = summary
            cache_dirty = True
            fetches_since_save += 1
            time.sleep(0.15)
            if fetches_since_save >= save_every:
                write_awards_cache(cache_path, cache)
                cache_dirty = False
                fetches_since_save = 0

        rows.append({"player_id": int(player_id), **summary})
        if index % 100 == 0 or index == total:
            print(f"awards progress: {index}/{total}")
        if (
            max_new_lookups > 0
            and new_lookups >= max_new_lookups
            and not budget_notice_printed
        ):
            print(f"awards lookup budget reached ({new_lookups} new players); using cache/zeros for remaining players")
            budget_notice_printed = True
        if (
            max_seconds > 0
            and (time.monotonic() - started_at) >= max_seconds
            and not awards_network_unavailable
            and not time_notice_printed
        ):
            print(f"awards time budget reached ({max_seconds}s); using cache/zeros for remaining players")
            time_notice_printed = True

    if cache_dirty:
        write_awards_cache(cache_path, cache)

    awards_df = pd.DataFrame(rows)
    if awards_df.empty:
        return pd.DataFrame(columns=AWARD_SUMMARY_COLUMNS)
    return awards_df[AWARD_SUMMARY_COLUMNS]


def percentile_by_role(
    values_df: pd.DataFrame,
    value_column: str,
    role_column: str,
    complete_mask: pd.Series,
    min_role_samples: int = 25,
) -> np.ndarray:
    global_distribution = np.sort(
        values_df.loc[complete_mask, value_column].to_numpy(dtype=float)
    )
    percentiles = empirical_percentile(
        global_distribution,
        values_df[value_column].to_numpy(dtype=float),
    )

    for role in POSITION_SCORE_WEIGHTS:
        role_complete = values_df.loc[
            complete_mask & (values_df[role_column] == role),
            value_column,
        ].to_numpy(dtype=float)
        if role_complete.size < min_role_samples:
            continue

        role_distribution = np.sort(role_complete)
        role_mask = values_df[role_column] == role
        percentiles[role_mask.to_numpy()] = empirical_percentile(
            role_distribution,
            values_df.loc[role_mask, value_column].to_numpy(dtype=float),
        )

    return percentiles


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
    ensure_nba_api_available("Draft history fetch")
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
                "playerPosition": (
                    row.get("POSITION")
                    or row.get("PLAYER_POSITION")
                    or row.get("POSITION_DESCRIPTION")
                    or ""
                ),
                "organization": row.get("ORGANIZATION", ""),
            }
        )
    return picks


def fetch_season_stats(season_start: int) -> pd.DataFrame:
    """Fetch league-wide player totals for one NBA season."""
    ensure_nba_api_available("Season stats fetch")
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


def compute_pick_scores(
    picks_df: pd.DataFrame,
    season_stats_df: pd.DataFrame,
    awards_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    score_columns = [
        "year",
        "round",
        "pick",
        "player_id",
        "team",
        "player",
        "pos",
        "position_bucket",
        "seasons_captured",
        "window_seasons",
        "gp",
        "min",
        "pts",
        "reb",
        "ast",
        "stl",
        "blk",
        "dreb",
        "projected_value",
        "expected_value",
        "surplus_value",
        "defense_impact",
        "awards_points",
        "score",
        "confidence",
        "score_band",
        "methodology_version",
    ]
    eligible_picks = picks_df[picks_df["player_id"].notna()].copy()
    if eligible_picks.empty or season_stats_df.empty:
        return pd.DataFrame(columns=score_columns)

    eligible_picks["player_id"] = eligible_picks["player_id"].astype(int)
    eligible_picks["pos"] = eligible_picks["pos"].fillna("").astype(str)
    eligible_picks["position_bucket"] = eligible_picks["pos"].apply(infer_role_bucket)

    merged = eligible_picks[
        ["year", "round", "pick", "player_id", "team", "player", "pos", "position_bucket"]
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
            ["year", "round", "pick", "player_id", "team", "player", "pos", "position_bucket"],
            as_index=False,
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
            dreb=("dreb", "sum"),
        )
    )

    result = eligible_picks.merge(
        grouped,
        on=["year", "round", "pick", "player_id", "team", "player", "pos", "position_bucket"],
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
        "dreb": 0.0,
    }
    result = result.fillna(numeric_fill)
    result["seasons_captured"] = result["seasons_captured"].astype(int)

    latest_season_start = int(season_stats_df["season_start"].max())
    result["window_seasons"] = (latest_season_start - result["year"] + 1).clip(lower=0, upper=5)

    projection_factor = np.where(result["window_seasons"] > 0, 5.0 / result["window_seasons"], 0.0)
    for metric in (*CORE_METRICS, "dreb"):
        result[f"proj_{metric}"] = result[metric] * projection_factor

    complete_mask = result["window_seasons"] >= 5

    for metric in CORE_METRICS:
        result[f"{metric}_pct"] = percentile_by_role(
            result,
            value_column=f"proj_{metric}",
            role_column="position_bucket",
            complete_mask=complete_mask,
        )
        result[f"{metric}_weight"] = result["position_bucket"].apply(
            lambda role: metric_weight_for_role(role, metric)
        )
        result[f"{metric}_weighted"] = result[f"{metric}_pct"] * result[f"{metric}_weight"]

    result["projected_value"] = sum(result[f"{metric}_weighted"] for metric in CORE_METRICS)
    complete = result[complete_mask].copy()
    if complete.empty:
        return pd.DataFrame(columns=score_columns)

    expected_by_pick: dict[int, float] = {}
    for pick_num in sorted(complete["pick"].unique()):
        slot_window = result[
            complete_mask
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

    if awards_df is None or awards_df.empty:
        awards_enrichment = pd.DataFrame(columns=AWARD_SUMMARY_COLUMNS)
    else:
        awards_enrichment = awards_df.copy()
        awards_enrichment["player_id"] = awards_enrichment["player_id"].astype(int)
        awards_enrichment = awards_enrichment.drop_duplicates(subset=["player_id"], keep="last")

    result = result.merge(awards_enrichment, on="player_id", how="left")
    for col in AWARD_SUMMARY_COLUMNS[1:]:
        if col not in result.columns:
            result[col] = 0.0
    result[AWARD_SUMMARY_COLUMNS[1:]] = result[AWARD_SUMMARY_COLUMNS[1:]].fillna(0.0)
    complete_mask = result["window_seasons"] >= 5

    quality_distribution = np.sort(result.loc[complete_mask, "projected_value"].to_numpy(dtype=float))
    surplus_distribution = np.sort(result.loc[complete_mask, "surplus_value"].to_numpy(dtype=float))
    awards_distribution = np.sort(result.loc[complete_mask, "awards_points"].to_numpy(dtype=float))
    defense_awards_distribution = np.sort(
        result.loc[complete_mask, "defense_awards_points"].to_numpy(dtype=float)
    )

    result["quality_pct"] = empirical_percentile(
        quality_distribution,
        result["projected_value"].to_numpy(dtype=float),
    )
    result["surplus_pct"] = empirical_percentile(
        surplus_distribution,
        result["surplus_value"].to_numpy(dtype=float),
    )
    result["awards_pct"] = empirical_percentile(
        awards_distribution,
        result["awards_points"].to_numpy(dtype=float),
    )

    minutes = result["proj_min"].clip(lower=1.0)
    result["proj_stl_per36"] = result["proj_stl"] * 36.0 / minutes
    result["proj_blk_per36"] = result["proj_blk"] * 36.0 / minutes
    result["proj_dreb_per36"] = result["proj_dreb"] * 36.0 / minutes

    result["def_stl_pct"] = percentile_by_role(
        result,
        value_column="proj_stl_per36",
        role_column="position_bucket",
        complete_mask=complete_mask,
    )
    result["def_blk_pct"] = percentile_by_role(
        result,
        value_column="proj_blk_per36",
        role_column="position_bucket",
        complete_mask=complete_mask,
    )
    result["def_dreb_pct"] = percentile_by_role(
        result,
        value_column="proj_dreb_per36",
        role_column="position_bucket",
        complete_mask=complete_mask,
    )

    result["defense_box_impact"] = (
        result["def_stl_pct"]
        * result["position_bucket"].apply(lambda role: defense_metric_weight_for_role(role, "stl"))
        + result["def_blk_pct"]
        * result["position_bucket"].apply(lambda role: defense_metric_weight_for_role(role, "blk"))
        + result["def_dreb_pct"]
        * result["position_bucket"].apply(lambda role: defense_metric_weight_for_role(role, "dreb"))
    )
    result["defense_awards_pct"] = empirical_percentile(
        defense_awards_distribution,
        result["defense_awards_points"].to_numpy(dtype=float),
    )
    result["defense_impact"] = (
        0.80 * result["defense_box_impact"] + 0.20 * result["defense_awards_pct"]
    ).clip(lower=0.0, upper=1.0)

    result["mature_score"] = 100.0 * (
        0.30 * result["quality_pct"]
        + 0.35 * result["surplus_pct"]
        + 0.20 * result["defense_impact"]
        + 0.15 * result["awards_pct"]
    )
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
            pos TEXT,
            position_bucket TEXT,
            seasons_captured INTEGER NOT NULL,
            window_seasons INTEGER NOT NULL,
            gp REAL NOT NULL,
            min REAL NOT NULL,
            pts REAL NOT NULL,
            reb REAL NOT NULL,
            ast REAL NOT NULL,
            stl REAL NOT NULL,
            blk REAL NOT NULL,
            dreb REAL NOT NULL,
            projected_value REAL,
            expected_value REAL,
            surplus_value REAL,
            defense_impact REAL,
            awards_points REAL,
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
            "Fetch historical NBA draft picks, season totals, player awards, and a 0-100 "
            "draft pick score into SQLite."
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
    parser.add_argument(
        "--skip-awards",
        action="store_true",
        help="skip player awards enrichment (faster, but score omits honors impact)",
    )
    parser.add_argument(
        "--awards-cache-path",
        default=str(DEFAULT_AWARDS_CACHE_PATH),
        help="JSON cache path for PlayerAwards lookups",
    )
    parser.add_argument(
        "--refresh-awards-cache",
        action="store_true",
        help="ignore cached awards entries and refetch from API",
    )
    parser.add_argument(
        "--awards-save-every",
        type=int,
        default=DEFAULT_AWARDS_SAVE_EVERY,
        help="write awards cache checkpoint every N fresh award lookups",
    )
    parser.add_argument(
        "--awards-max-new-lookups",
        type=int,
        default=0,
        help="max number of uncached awards API lookups this run (0 = no limit)",
    )
    parser.add_argument(
        "--awards-max-seconds",
        type=int,
        default=0,
        help="time budget in seconds for awards API calls this run (0 = no limit)",
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
    awards_cache_path = Path(args.awards_cache_path)
    all_picks: list[dict] = []
    draft_network_failed = False
    draft_fallback_only = False

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
            elif draft_fallback_only:
                raw_picks = generate_sample_picks(year)
                print(f"{year}: using fallback sample picks (network unavailable in earlier year)")
            else:
                raw_picks = run_with_retries(
                    f"draft {year}",
                    lambda: fetch_draft_year(year),
                )
                print(f"{year}: fetched {len(raw_picks)} picks")
        except Exception as exc:
            if "requires 'nba_api'" in str(exc):
                raise SystemExit(str(exc))
            draft_network_failed = True
            print(f"failed {year}: {exc}")
            if not args.local_dir:
                raw_picks = generate_sample_picks(year)
                print(f"{year}: generated {len(raw_picks)} fallback sample picks")
                # Avoid repeated slow retries across every remaining year when network is blocked.
                if looks_like_network_unreachable(exc):
                    draft_fallback_only = True

        for raw_pick in raw_picks:
            record = normalize_pick_record(year, raw_pick)
            if record is not None:
                all_picks.append(record)
        time.sleep(0.5)

    picks_df = pd.DataFrame(all_picks).sort_values(["year", "pick"], ascending=[True, True]).reset_index(drop=True)
    if picks_df.empty:
        raise SystemExit("no draft picks were loaded")

    season_stats_df = pd.DataFrame()
    awards_df = pd.DataFrame(columns=AWARD_SUMMARY_COLUMNS)
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
            if args.skip_awards:
                print("skipping awards enrichment (--skip-awards)")
            else:
                try:
                    player_ids = (
                        picks_df.loc[picks_df["player_id"].notna(), "player_id"]
                        .astype(int)
                        .drop_duplicates()
                        .tolist()
                    )
                    awards_df = fetch_awards_summaries(
                        player_ids=player_ids,
                        cache_path=awards_cache_path,
                        refresh_cache=args.refresh_awards_cache,
                        save_every=args.awards_save_every,
                        max_new_lookups=args.awards_max_new_lookups,
                        max_seconds=args.awards_max_seconds,
                    )
                    print(f"loaded award summaries for {len(awards_df)} players")
                except Exception as exc:
                    print(f"awards enrichment failed, continuing without awards: {exc}")
                    awards_df = pd.DataFrame(columns=AWARD_SUMMARY_COLUMNS)

            scores_df = compute_pick_scores(picks_df, season_stats_df, awards_df=awards_df)
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
