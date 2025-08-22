# src/ui/css_loader.py

from __future__ import annotations
from pathlib import Path
import streamlit as st

# Cache so we don't re-read the same CSS file on every rerun
@st.cache_resource
def _read_text(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSS file not found: {p.resolve()}")
    return p.read_text(encoding="utf-8")

def load_css(*paths: str | Path) -> None:
    """
    Inject one or more CSS files into the Streamlit app.
    Usage: load_css("assets/custom.css", "assets/other.css")
    """
    chunks = []
    for path in paths:
        chunks.append(_read_text(path))
    css = "\n\n".join(chunks)
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)