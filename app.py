import streamlit as st

from src.ui.css_loader import load_css
from src.ui.countdown import render_countdown

st.set_page_config(page_title="Draft Craft", layout="wide")

# Shared app styling
load_css("assets/custom.css")

# Shared sidebar
with st.sidebar:
    render_countdown()
    st.image("assets/logo_dc.png", width=180)
    st.markdown("### Draft Craft")
    st.caption("NBA Draft tracking & insights")

# Define navigation explicitly so only desired pages are shown.
pg = st.navigation(
    [
        st.Page("pages/0_draft_board.py", title="Draft Board"),
    ]
)
pg.run()
