from __future__ import annotations

import streamlit as st

LOADING_OVERLAY_HTML = """
<div class="dc-loading-overlay" role="status" aria-live="polite" aria-label="Loading">
    <div class="dc-ball-wrap" aria-hidden="true">
        <div class="dc-basketball"></div>
        <div class="dc-ball-shadow"></div>
    </div>
</div>
"""


def show_loading_overlay():
    placeholder = st.empty()
    placeholder.markdown(LOADING_OVERLAY_HTML, unsafe_allow_html=True)
    return placeholder
