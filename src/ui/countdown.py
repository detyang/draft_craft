# src/ui/countdown.py

from __future__ import annotations
from datetime import datetime, date, time as dt_time, timedelta
from zoneinfo import ZoneInfo
import streamlit as st
import html

NBA_TZ = ZoneInfo("America/New_York")


def _last_thursday_of_june(year: int) -> date:
    d = date(year, 6, 30)
    while d.weekday() != 3:  # Thursday=3
        d -= timedelta(days=1)
    return d

def next_draft_datetime_et() -> datetime:
    """Default rule: last Thursday of June, 7:00 PM ET."""
    now_et = datetime.now(NBA_TZ)
    this_year = datetime.combine(_last_thursday_of_june(now_et.year), dt_time(19, 0), tzinfo=NBA_TZ)
    return this_year if now_et < this_year else datetime.combine(
        _last_thursday_of_june(now_et.year + 1), dt_time(19, 0), tzinfo=NBA_TZ
    )

def render_countdown(color: str = "#00C2FF") -> None:
    target_dt = next_draft_datetime_et()
    now = datetime.now(NBA_TZ)
    days_left = max(0, (target_dt.date() - now.date()).days)
    year = target_dt.year
    st.markdown(
        f"""
        <div style="font-size:1rem;">
            <span style="font-weight:700; color:{color};">{days_left}</span> days until {year} NBA Draft
        </div>
        """,
        unsafe_allow_html=True,
    )
