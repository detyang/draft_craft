import streamlit as st
import pandas as pd
from datetime import datetime

from src.data.mock_sources import fetch_all_sources

st.title("Draft Board - Mock Draft Sources")


@st.cache_data(ttl=60 * 30)
def get_mock_board() -> pd.DataFrame:
    data = fetch_all_sources()
    df = pd.DataFrame(data)
    df = df.dropna(subset=["Pick"])
    df = df.sort_values(["Source", "Pick"], kind="stable").reset_index(drop=True)
    return df


with st.spinner("Fetching latest mock drafts..."):
    df = get_mock_board()

st.subheader("Tankathon")
tankathon_df = (
    df[df["Source"] == "Tankathon"][["Pick", "Team", "Player", "Pos"]]
    .sort_values("Pick", kind="stable")
    .reset_index(drop=True)
)
st.dataframe(tankathon_df, use_container_width=True, hide_index=True)

st.subheader("NBADraft.net")
nbadraft_df = (
    df[df["Source"] == "NBADraft.net"][["Pick", "Team", "Player", "Pos"]]
    .sort_values("Pick", kind="stable")
    .reset_index(drop=True)
)
st.dataframe(nbadraft_df, use_container_width=True, hide_index=True)

st.caption(f"Sources: Tankathon, NBADraft.net - Last updated: {datetime.now():%Y-%m-%d %H:%M:%S}")
