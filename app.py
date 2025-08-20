import streamlit as st

st.set_page_config(page_title="Draft Craft", layout="wide")

# Sidebar
with st.sidebar:
    st.image("assets/logo_dc.png", width=180)
    st.markdown("### Draft Craft")
    st.caption("NBA Draft tracking & insights")

st.title("Draft Craft")
st.caption("This is caption")