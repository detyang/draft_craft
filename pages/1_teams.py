import streamlit as st
import pandas as pd

from src.data.historical_drafts import (
    get_historical_picks_for_team,
    get_data_last_updated,
)

st.title("Teams - Historical Draft Picks")

# List of NBA teams
teams = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
]

# Dropdown to select team
selected_team = st.selectbox("Select a Team", teams)

if selected_team:
    # prepare update date early to use after data view
    updated = get_data_last_updated()

    picks = get_historical_picks_for_team(selected_team)

    if picks:
        # Convert to DataFrame for display
        df = pd.DataFrame([{
            "Year": pick.year,
            "Round": pick.round,
            "Pick": pick.pick,
            "Player": pick.player,
            "Position": pick.pos,
            "Organization": pick.organization
        } for pick in picks])

        # Sort by year descending
        df = df.sort_values("Year", ascending=False).reset_index(drop=True)

        # Only include Position column if it has data
        cols = ["Year", "Round", "Pick", "Player", "Organization"]
        if df["Position"].notna().any() and (df["Position"] != "").any():
            cols.insert(4, "Position")

        st.dataframe(df[cols], use_container_width=True, hide_index=True)
        # footer note below the table
        st.caption(f"Historical Draft Picks (data last updated: {updated})")
    else:
        st.write("No historical picks found for this team.")
        st.info("If you see errors in the console about network or SSL, you may need to supply a local cache file `src/data/historical_cache.json`.")
        # still show update info even when no picks
        st.caption(f"Historical Draft Picks (data last updated: {updated})")