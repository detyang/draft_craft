from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

_ROOT_DIR = Path(__file__).resolve().parents[2]
_BASKETBALL_PATH = _ROOT_DIR / "assets" / "basketball.png"


@lru_cache(maxsize=1)
def _basketball_data_uri() -> str:
    encoded = base64.b64encode(_BASKETBALL_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _loading_overlay_html() -> str:
    return f"""
<div class="dc-loading-overlay" role="status" aria-live="polite" aria-label="Loading">
    <div class="dc-ball-wrap" aria-hidden="true">
        <img class="dc-basketball" src="{_basketball_data_uri()}" alt="" />
        <div class="dc-ball-shadow"></div>
    </div>
</div>
"""


def show_loading_overlay():
    placeholder = st.empty()
    placeholder.markdown(_loading_overlay_html(), unsafe_allow_html=True)
    return placeholder
