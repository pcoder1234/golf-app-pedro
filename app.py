"""
app.py
Golf Stats & Insights — Streamlit MVP

Run with:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import date
import plotly.express as px

import db
import analysis

st.set_page_config(page_title="Golf Stats & Insights", page_icon="⛳", layout="wide")
db.init_db()

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("⛳ Golf Stats")
page = st.sidebar.radio(
    "Navigate",
    ["Enter Round", "Dashboard", "Insights & Strategy", "Course Setup", "Round History"],
)

# ---------------------------------------------------------------------------
# PAGE: Enter Round
# ---------------------------------------------------------------------------
if page == "Enter Round":
    st.title("Enter a Round")

    with st.form("round_meta"):
        col1, col2, col3 = st.columns(3)
        with col1:
            round_date = st.date_input("Date", value=date.today())
            course_name = st.text_input("Course name", placeholder="e.g. Pebble Beach")
        with col2:
            tees = st.text_input("Tees played", placeholder="e.g. White")
            num_holes = st.selectbox("Holes played", [18, 9], index=0)
        with col3:
            weather = st.text_input("Weather (optional)", placeholder="e.g. Windy, 60F")
            notes = st.text_input("Notes (optional)")

        st.markdown("---")
        st.subheader("Hole-by-hole entry")

        # Pre-fill from saved course layout if available
        saved_courses = db.get_course_names()
        prefill = pd.DataFrame()
        if course_name in saved_courses:
            prefill = db.get_course_layout(course_name)

        default_rows = []
        for i in range(1, num_holes + 1):
            if not prefill.empty and i in prefill["hole_number"].values:
                r = prefill[prefill["hole_number"] == i].iloc[0]
                par = int(r["par"])
                yardage = int(r["yardage"]) if pd.notna(r["yardage"]) else 400
            else:
                par = 4
                yardage = 400
            default_rows.append({
                "hole_number": i,
                "par": par,
                "yardage": yardage,
                "score": par,
                "putts": 2,
                "fairway_hit": "N/A" if par == 3 else "Yes",
                "gir": "No",
                "penalties": 0,
            })
        default_df = pd.DataFrame(default_rows)

        edited_df = st.data_editor(
            default_df,
            column_config={
                "hole_number": st.column_config.NumberColumn("Hole", disabled=True),
                "par": st.column_config.SelectboxColumn("Par", options=[3, 4, 5]),
                "yardage": st.column_config.NumberColumn("Yardage", min_value=50, max_value=700),
                "score": st.column_config.NumberColumn("Score", min_value=1, max_value=15),
                "putts": st.column_config.NumberColumn("Putts", min_value=0, max_value=8),
                "fairway_hit": st.column_config.SelectboxColumn("Fairway Hit", options=["Yes", "No", "N/A"]),
                "gir": st.column_config.SelectboxColumn("GIR", options=["Yes", "No"]),
                "penalties": st.column_config.NumberColumn("Penalty Strokes", min_value=0, max_value=5),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
        )

        submitted = st.form_submit_button("Save Round", type="primary")

        if submitted:
            if not course_name.strip():
                st.error("Please enter a course name.")
            else:
                db.save_round(
                    round_date, course_name.strip(), tees, None, None, weather, notes, edited_df
                )
                st.success(f"Round saved! Total score: {edited_df['score'].sum()} on {course_name}")
                st.balloons()

# ---------------------------------------------------------------------------
# PAGE: Dashboard
# ---------------------------------------------------------------------------
elif page == "Dashboard":
    st.title("Your Stats Dashboard")

    rounds_df = db.get_all_rounds()
    all_holes = db.get_all_holes_joined()

    if rounds_df.empty:
        st.info("No rounds logged yet. Head to **Enter Round** to add your first one.")
    else:
        # Compute score_to_par per round for trend chart
        rounds_calc = []
        for rid in rounds_df["id"]:
            holes = db.get_holes_for_round(rid)
            summary = analysis.round_summary(holes)
            row = rounds_df[rounds_df["id"] == rid].iloc[0].to_dict()
            row.update(summary)
            rounds_calc.append(row)
        rounds_calc_df = pd.DataFrame(rounds_calc)

        # --- Top-line metrics ---
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Rounds Logged", len(rounds_df))
        col2.metric("Avg Score to Par", f"{rounds_calc_df['score_to_par'].mean():+.1f}")
        col3.metric("Avg Putts/Round", f"{rounds_calc_df['putts'].mean():.1f}")
        col4.metric("Avg GIR%", f"{rounds_calc_df['gir_pct'].mean():.0f}%")

        st.markdown("---")

        # --- Trend chart ---
        st.subheader("Score to Par Over Time")
        trend_df = analysis.trend_over_time(rounds_calc_df)
        fig = px.line(
            trend_df, x="round_date", y="score_to_par", markers=True,
            labels={"round_date": "Date", "score_to_par": "Score to Par"},
        )
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig, use_container_width=True)

        # --- Scoring by par type ---
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Scoring by Par Type")
            by_par = analysis.scoring_by_par_type(all_holes)
            fig2 = px.bar(
                by_par, x="Par", y="avg_to_par",
                labels={"avg_to_par": "Avg Score to Par"},
                color="avg_to_par", color_continuous_scale="RdYlGn_r",
            )
            fig2.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig2, use_container_width=True)

        with col_b:
            st.subheader("Fairways / GIR / Putts by Round")
            fig3 = px.bar(
                rounds_calc_df, x="round_date", y=["fairways_hit_pct", "gir_pct"],
                barmode="group", labels={"value": "%", "round_date": "Date"},
            )
            st.plotly_chart(fig3, use_container_width=True)

        st.subheader("All Rounds")
        display_cols = [
            "round_date", "course_name", "tees", "total_score", "score_to_par",
            "putts", "gir_pct", "fairways_hit_pct", "penalties",
        ]
        st.dataframe(
            rounds_calc_df[[c for c in display_cols if c in rounds_calc_df.columns]],
            use_container_width=True, hide_index=True,
        )

# ---------------------------------------------------------------------------
# PAGE: Insights & Strategy
# ---------------------------------------------------------------------------
elif page == "Insights & Strategy":
    st.title("Insights & Strategy")

    rounds_df = db.get_all_rounds()
    all_holes = db.get_all_holes_joined()

    st.subheader("What your data says")
    insights = analysis.generate_insights(all_holes, rounds_df)
    for ins in insights:
        if ins["severity"] == "warn":
            st.warning(f"**{ins['headline']}**\n\n{ins['detail']}")
        else:
            st.info(f"**{ins['headline']}**\n\n{ins['detail']}")

    st.markdown("---")
    st.subheader("Pre-Round Strategy by Hole")
    st.caption(
        "Set up a course's hole-by-hole layout under **Course Setup**, then pick it here "
        "to get hole-specific strategy notes based on your tendencies."
    )

    courses = db.get_course_names()
    if not courses:
        st.info("No course layouts saved yet. Add one under **Course Setup**.")
    else:
        chosen_course = st.selectbox("Choose a course", courses)
        layout = db.get_course_layout(chosen_course)
        strategy_df = analysis.hole_strategy_notes(layout, insights)
        st.dataframe(strategy_df, use_container_width=True, hide_index=True)
        st.caption(
            "This is a rules-based first pass. A natural next step is piping these same "
            "stats + course notes into an LLM call for a fuller, more conversational game plan."
        )

# ---------------------------------------------------------------------------
# PAGE: Course Setup
# ---------------------------------------------------------------------------
elif page == "Course Setup":
    st.title("Course Setup")
    st.caption("Save a course's hole-by-hole layout once, then reuse it for score entry and strategy notes.")

    with st.form("course_setup"):
        course_name = st.text_input("Course name")
        num_holes = st.selectbox("Number of holes", [18, 9], index=0)

        default_rows = [
            {"hole_number": i, "par": 4, "yardage": 400, "handicap_index": i, "hazard_notes": ""}
            for i in range(1, num_holes + 1)
        ]
        layout_df = st.data_editor(
            pd.DataFrame(default_rows),
            column_config={
                "hole_number": st.column_config.NumberColumn("Hole", disabled=True),
                "par": st.column_config.SelectboxColumn("Par", options=[3, 4, 5]),
                "yardage": st.column_config.NumberColumn("Yardage", min_value=50, max_value=700),
                "handicap_index": st.column_config.NumberColumn("Hole Handicap", min_value=1, max_value=18),
                "hazard_notes": st.column_config.TextColumn("Hazard Notes", width="large"),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
        )

        saved = st.form_submit_button("Save Course Layout", type="primary")
        if saved:
            if not course_name.strip():
                st.error("Please enter a course name.")
            else:
                db.upsert_course_holes(course_name.strip(), layout_df)
                st.success(f"Saved layout for {course_name}.")

# ---------------------------------------------------------------------------
# PAGE: Round History
# ---------------------------------------------------------------------------
elif page == "Round History":
    st.title("Round History")

    rounds_df = db.get_all_rounds()
    if rounds_df.empty:
        st.info("No rounds logged yet.")
    else:
        for _, r in rounds_df.iterrows():
            with st.expander(f"{r['round_date']} — {r['course_name']} ({r['tees'] or 'N/A'} tees)"):
                holes = db.get_holes_for_round(r["id"])
                summary = analysis.round_summary(holes)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Score", f"{summary['total_score']} ({summary['score_to_par']:+d})")
                c2.metric("Putts", summary["putts"])
                c3.metric("GIR%", f"{summary['gir_pct']}%")
                c4.metric("Penalties", summary["penalties"])
                st.dataframe(holes.drop(columns=["id", "round_id"]), use_container_width=True, hide_index=True)
                if st.button("Delete this round", key=f"del_{r['id']}"):
                    db.delete_round(r["id"])
                    st.rerun()
