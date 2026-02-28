import streamlit as st
import pandas as pd
from datetime import datetime

from src.data.mock_sources import fetch_all_sources

st.title("🏀 Draft Board — Tankathon Mock Draft")

@st.cache_data(ttl=60 * 30)
def get_tankathon_board() -> pd.DataFrame:
    data = fetch_all_sources()
    df = pd.DataFrame(data)
    df = df.dropna(subset=["Pick"])
    df = df.sort_values("Pick", kind="stable").reset_index(drop=True)
    return df

with st.spinner("Fetching latest mock draft from Tankathon..."):
    df = get_tankathon_board()

# Show a clean table
st.subheader("Round 1 — Tankathon mock")
st.dataframe(
    df[["Pick", "Team", "Player", "Pos"]],
    use_container_width=True,
    hide_index=True,
)

st.caption(f"Source: Tankathon mock draft • Last updated: {datetime.now():%Y-%m-%d %H:%M:%S}")

with st.expander("Raw data (debug)"):
    st.dataframe(df, use_container_width=True, hide_index=True)