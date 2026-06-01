"""Streamlit dashboard for browsing the audio sample catalog.

Provides interactive filters, statistics cards, charts, and a
searchable data table over the SQLite sample database.

Launch:
    streamlit run python/scripts/sample_dashboard.py
"""

import sys
from pathlib import Path

# Add parent to path so stresscon package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px

from stresscon.sample_db import SampleDB

# --- Page config ---
st.set_page_config(
    page_title="Sample Library",
    page_icon="🎵",
    layout="wide",
)


@st.cache_data(ttl=60)
def load_data(db_path: str) -> pd.DataFrame:
    """Load all samples from the database, cached for 60 seconds."""
    with SampleDB(Path(db_path)) as db:
        return db.get_all()


@st.cache_data(ttl=60)
def load_stats(db_path: str) -> dict:
    """Load catalog statistics, cached for 60 seconds."""
    with SampleDB(Path(db_path)) as db:
        return db.get_stats()


def resolve_db_path() -> Path:
    """Resolve the SQLite database path."""
    return Path(__file__).resolve().parent.parent / "data" / "samples.db"


def main() -> None:
    db_path = resolve_db_path()

    if not db_path.exists():
        st.error(
            f"Database not found at `{db_path}`.\n\n"
            "Run the scanner first:\n\n"
            "```bash\n"
            "python python/scripts/scan_samples.py --samples-dir ~/Music/Samples\n"
            "```"
        )
        return

    df = load_data(str(db_path))

    if df.empty:
        st.warning(
            "Database is empty. Run the scanner to populate it:\n\n"
            "```bash\n"
            "python python/scripts/scan_samples.py --samples-dir ~/Music/Samples\n"
            "```"
        )
        return

    stats = load_stats(str(db_path))

    # === SIDEBAR FILTERS ===
    st.sidebar.title("Sample Library")
    st.sidebar.markdown("---")

    # Search
    search_query = st.sidebar.text_input("Search filename", placeholder="kick, snare, pad...")

    # Format filter
    available_formats = sorted(df["format"].dropna().unique().tolist())
    selected_formats = st.sidebar.multiselect("Format", available_formats, default=available_formats)

    # Category filter
    available_categories = sorted(df["category"].dropna().unique().tolist())
    selected_categories = st.sidebar.multiselect("Category", available_categories, default=available_categories)

    # Sample type filter
    type_options = ["All", "Loop", "One-Shot"]
    selected_type = st.sidebar.radio("Type", type_options, horizontal=True)

    # BPM range
    bpm_samples = df[df["bpm"].notna()]
    if not bpm_samples.empty:
        bpm_min_val = float(bpm_samples["bpm"].min())
        bpm_max_val = float(bpm_samples["bpm"].max())
        bpm_range = st.sidebar.slider(
            "BPM Range",
            min_value=bpm_min_val,
            max_value=bpm_max_val,
            value=(bpm_min_val, bpm_max_val),
            step=1.0,
        )
    else:
        bpm_range = (0.0, 300.0)

    # Key filter
    available_keys = sorted(df["musical_key"].dropna().unique().tolist())
    selected_keys = st.sidebar.multiselect("Musical Key", ["All"] + available_keys, default=["All"])

    # Duration range
    if df["duration_seconds"].notna().any():
        dur_min = float(df["duration_seconds"].min())
        dur_max = float(df["duration_seconds"].max())
        dur_range = st.sidebar.slider(
            "Duration (seconds)",
            min_value=dur_min,
            max_value=dur_max,
            value=(dur_min, dur_max),
            step=0.1,
        )
    else:
        dur_range = (0.0, 600.0)

    st.sidebar.markdown("---")

    # Actions
    if st.sidebar.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    if st.sidebar.button("Clean Stale Entries"):
        with SampleDB(db_path) as db:
            deleted = db.delete_missing()
        st.sidebar.success(f"Removed {deleted} stale entries")
        st.cache_data.clear()
        st.rerun()

    # === APPLY FILTERS ===
    filtered = df.copy()

    if search_query:
        filtered = filtered[filtered["filename"].str.contains(search_query, case=False, na=False)]

    filtered = filtered[filtered["format"].isin(selected_formats)]
    filtered = filtered[filtered["category"].isin(selected_categories)]

    if selected_type == "Loop":
        filtered = filtered[filtered["sample_type"] == "loop"]
    elif selected_type == "One-Shot":
        filtered = filtered[filtered["sample_type"] == "one-shot"]

    # BPM filter: include samples with no BPM (non-rhythmic content)
    has_bpm = filtered["bpm"].notna()
    in_range = (filtered["bpm"] >= bpm_range[0]) & (filtered["bpm"] <= bpm_range[1])
    filtered = filtered[~has_bpm | in_range]

    if "All" not in selected_keys:
        filtered = filtered[filtered["musical_key"].isin(selected_keys)]

    if df["duration_seconds"].notna().any():
        filtered = filtered[
            (filtered["duration_seconds"] >= dur_range[0])
            & (filtered["duration_seconds"] <= dur_range[1])
        ]

    # === MAIN AREA ===

    # Row 1: Stats cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Samples", f"{len(filtered):,}")
    with col2:
        avg_bpm = filtered["bpm"].dropna().mean()
        st.metric("Avg BPM", f"{avg_bpm:.1f}" if pd.notna(avg_bpm) else "N/A")
    with col3:
        total_dur = filtered["duration_seconds"].sum()
        hours = total_dur / 3600
        if hours >= 1:
            st.metric("Total Duration", f"{hours:.1f} hrs")
        else:
            st.metric("Total Duration", f"{total_dur / 60:.1f} min")
    with col4:
        total_mb = filtered["file_size_bytes"].sum() / (1024 * 1024)
        st.metric("Total Size", f"{total_mb:.1f} MB")

    st.markdown("---")

    # Row 2: Charts
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        if not filtered.empty:
            cat_counts = filtered["category"].value_counts().reset_index()
            cat_counts.columns = ["Category", "Count"]
            fig = px.pie(
                cat_counts, values="Count", names="Category",
                title="Category Distribution",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)

    with chart_col2:
        bpm_data = filtered[filtered["bpm"].notna()]
        if not bpm_data.empty:
            fig = px.histogram(
                bpm_data, x="bpm", nbins=30,
                title="BPM Distribution",
                labels={"bpm": "BPM"},
                color_discrete_sequence=["#636EFA"],
            )
            fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No BPM data available for chart")

    chart_col3, chart_col4 = st.columns(2)

    with chart_col3:
        key_data = filtered[filtered["musical_key"].notna()]
        if not key_data.empty:
            key_counts = key_data["musical_key"].value_counts().reset_index()
            key_counts.columns = ["Key", "Count"]
            fig = px.bar(
                key_counts.head(24), x="Key", y="Count",
                title="Key Distribution",
                color_discrete_sequence=["#EF553B"],
            )
            fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No key data available for chart")

    with chart_col4:
        dur_data = filtered[filtered["duration_seconds"].notna()]
        if not dur_data.empty:
            fig = px.histogram(
                dur_data, x="duration_seconds", nbins=40,
                title="Duration Distribution",
                labels={"duration_seconds": "Duration (s)"},
                color_discrete_sequence=["#00CC96"],
            )
            fig.update_layout(margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No duration data available for chart")

    st.markdown("---")

    # Row 3: Data table
    st.subheader(f"Samples ({len(filtered):,} results)")

    display_cols = [
        "filename", "format", "duration_seconds", "bpm", "musical_key",
        "category", "sample_type", "channels", "sample_rate", "file_path",
    ]
    available_display_cols = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[available_display_cols],
        use_container_width=True,
        height=500,
        column_config={
            "filename": st.column_config.TextColumn("Filename", width="medium"),
            "format": st.column_config.TextColumn("Format", width="small"),
            "duration_seconds": st.column_config.NumberColumn("Duration (s)", format="%.2f"),
            "bpm": st.column_config.NumberColumn("BPM", format="%.1f"),
            "musical_key": st.column_config.TextColumn("Key", width="small"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "sample_type": st.column_config.TextColumn("Type", width="small"),
            "channels": st.column_config.NumberColumn("Ch", width="small"),
            "sample_rate": st.column_config.NumberColumn("Sample Rate"),
            "file_path": st.column_config.TextColumn("Path", width="large"),
        },
    )


if __name__ == "__main__":
    main()
