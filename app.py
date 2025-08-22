import streamlit as st

from src.ui.css_loader import load_css
from src.ui.countdown import render_countdown

st.set_page_config(page_title="Draft Craft", layout="wide")

# Load your stylesheet(s)
load_css("assets/custom.css")

# Sidebar
with st.sidebar:
    render_countdown()
    st.image("assets/logo_dc.png", width=180)
    st.markdown("### Draft Craft")
    st.caption("NBA Draft tracking & insights")


st.title("Draft Craft")
st.caption("This is caption")