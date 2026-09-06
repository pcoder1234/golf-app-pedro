"""
analysis.py
Turns raw hole-level data into stats and plain-English insights.

This is intentionally NOT an LLM. It's the deterministic statistics layer —
the part that should be trustworthy and reproducible. An LLM (e.g. via the
Anthropic API) can later sit on TOP of this to turn these numbers into a
more conversational pre-round game plan, but the numbers themselves should
always come from real math, not a model guessing.
"""

import pandas as pd
import numpy as np


def score_to_par(df: pd.DataFrame) -> pd.Series:
    return df["score"] - df["par"]


def round_summary(holes_df: pd.DataFrame) -> dict:
    """Summary stats for a single round's holes."""
    if holes_df.empty:
        return {}

    total_score = holes_df["score"].sum()
    total_par = holes_df["par"].sum()
    putts = holes_df["putts"].sum()

    par4_5 = holes_df[holes_df["par"] >= 4]
    fw_opportunities = par4_5[par4_5["fairway_hit"].isin(["Yes", "No"])]
    fairways_hit_pct = (
        (fw_opportunities["fairway_hit"] == "Yes").mean() * 100
        if len(fw_opportunities) else np.nan
    )

    gir_pct = (holes_df["gir"] == "Yes").mean() * 100
    penalties = holes_df["penalties"].sum()

    three_putts = (holes_df["putts"] >= 3).sum()

    return {
        "total_score": int(total_score),
        "total_par": int(total_par),
        "score_to_par": int(total_score - total_par),
        "putts": int(putts),
        "putts_per_hole": round(putts / len(holes_df), 2),
        "fairways_hit_pct": round(fairways_hit_pct, 1) if pd.notna(fairways_hit_pct) else None,
        "gir_pct": round(gir_pct, 1),
        "penalties": int(penalties),
        "three_putts": int(three_putts),
        "holes_played": len(holes_df),
    }


def scoring_by_par_type(all_holes: pd.DataFrame) -> pd.DataFrame:
    """Average score-to-par broken down by par 3 / 4 / 5, across all rounds."""
    df = all_holes.copy()
    df["to_par"] = score_to_par(df)
    grouped = (
        df.groupby("par")["to_par"]
        .agg(avg_to_par="mean", holes_played="count")
        .reset_index()
        .rename(columns={"par": "Par"})
    )
    grouped["avg_to_par"] = grouped["avg_to_par"].round(2)
    return grouped


def trend_over_time(rounds_df: pd.DataFrame) -> pd.DataFrame:
    """Score-to-par per round over time, for a trend chart."""
    df = rounds_df.copy()
    df["round_date"] = pd.to_datetime(df["round_date"])
    df = df.sort_values("round_date")
    return df


def generate_insights(all_holes: pd.DataFrame, rounds_df: pd.DataFrame) -> list:
    """
    Rule-based coaching insights derived from the aggregated stats.
    Each insight is a dict: {"headline": str, "detail": str, "severity": "info"|"warn"}
    Severity just affects how it's styled in the UI (bigger issues = warn).
    """
    insights = []

    if all_holes.empty or len(rounds_df) < 2:
        insights.append({
            "headline": "Not enough data yet",
            "detail": "Log at least 2-3 rounds to start seeing meaningful trends and personalized insights.",
            "severity": "info",
        })
        return insights

    df = all_holes.copy()
    df["to_par"] = score_to_par(df)

    # --- Putting ---
    putts_per_hole = df["putts"].mean()
    three_putt_rate = (df["putts"] >= 3).mean() * 100
    if three_putt_rate > 12:
        insights.append({
            "headline": f"3-putts are costing you strokes ({three_putt_rate:.0f}% of holes)",
            "detail": (
                "A healthy target is under 8-10% of holes. Frequent 3-putts usually point to "
                "distance control on lag putts rather than the short stuff. Try spending more "
                "practice time on 30-50 foot lag putting to a small target rather than short putts."
            ),
            "severity": "warn",
        })
    elif putts_per_hole < 1.8:
        insights.append({
            "headline": "Your putting is a strength",
            "detail": f"You're averaging {putts_per_hole:.2f} putts/hole, which is strong. Your biggest score gains are likely elsewhere (see below).",
            "severity": "info",
        })

    # --- GIR ---
    gir_pct = (df["gir"] == "Yes").mean() * 100
    if gir_pct < 30:
        insights.append({
            "headline": f"Greens in regulation are low ({gir_pct:.0f}%)",
            "detail": (
                "Missing greens forces up-and-downs you may not be converting. Consider tracking "
                "your miss pattern (short/long/left/right) to see if approach club selection or "
                "contact is the bigger issue."
            ),
            "severity": "warn",
        })

    # --- Fairways ---
    fw_df = df[df["fairway_hit"].isin(["Yes", "No"])]
    if len(fw_df) > 0:
        fw_pct = (fw_df["fairway_hit"] == "Yes").mean() * 100
        if fw_pct < 40:
            insights.append({
                "headline": f"Driving accuracy is a leak ({fw_pct:.0f}% fairways)",
                "detail": (
                    "Missing over 60% of fairways usually means approach shots are starting from "
                    "trouble. Consider club-down strategy off the tee on tighter holes — "
                    "a 3-wood or hybrid in the fairway often beats a driver in the rough."
                ),
                "severity": "warn",
            })

    # --- Scoring by par type ---
    by_par = scoring_by_par_type(df)
    worst = by_par.loc[by_par["avg_to_par"].idxmax()]
    if worst["avg_to_par"] > 0.5:
        par_label = {3: "par 3s", 4: "par 4s", 5: "par 5s"}.get(int(worst["Par"]), f"par {int(worst['Par'])}s")
        insights.append({
            "headline": f"{par_label.capitalize()} are your weakest hole type",
            "detail": (
                f"You're averaging {worst['avg_to_par']:+.2f} relative to par on {par_label}, "
                f"your worst of the three. This is usually the highest-leverage area to focus practice on."
            ),
            "severity": "warn",
        })

    # --- Penalties ---
    penalty_rate = df["penalties"].sum() / len(rounds_df)
    if penalty_rate > 1.5:
        insights.append({
            "headline": f"Penalty strokes are adding up (~{penalty_rate:.1f}/round)",
            "detail": (
                "More than 1-1.5 penalty strokes per round is a meaningful leak. On holes with "
                "hazards, consider laying up or taking a more conservative line off the tee even "
                "if it costs some distance."
            ),
            "severity": "warn",
        })

    # --- Trend direction ---
    if len(rounds_df) >= 3:
        rounds_sorted = trend_over_time(rounds_df)
        rounds_sorted["to_par_round"] = rounds_sorted["total_score"] if "total_score" in rounds_sorted else None
        recent = rounds_sorted.tail(3)
        if "score_to_par" in rounds_sorted.columns:
            trend = recent["score_to_par"].values
            if len(trend) >= 2 and trend[-1] < trend[0]:
                insights.append({
                    "headline": "You're trending in the right direction",
                    "detail": "Your last few rounds show improving scores relative to par. Keep doing what you're doing.",
                    "severity": "info",
                })

    if not insights:
        insights.append({
            "headline": "Solid, well-rounded game",
            "detail": "No major statistical leaks detected across putting, GIR, fairways, or scoring by hole type. Keep logging rounds to refine this further.",
            "severity": "info",
        })

    return insights


def hole_strategy_notes(course_layout: pd.DataFrame, player_insights: list) -> pd.DataFrame:
    """
    Combine a course's hole-by-hole layout with the player's known weaknesses
    to produce simple per-hole strategy flags. This is a lightweight rules
    engine — a good place to later swap in an LLM call that takes this same
    course_layout + player stats and writes a fuller narrative.
    """
    if course_layout.empty:
        return pd.DataFrame()

    notes = []
    weak_areas = {i["headline"] for i in player_insights}
    driving_leak = any("Driving accuracy" in h for h in weak_areas)
    long_par4_leak = any("par 4s" in h for h in weak_areas)
    par5_leak = any("par 5s" in h for h in weak_areas)

    for _, row in course_layout.iterrows():
        tips = []
        if row["par"] == 4 and row["yardage"] and row["yardage"] >= 420 and long_par4_leak:
            tips.append("Long par 4 + this is a weak spot for you — prioritize fairway over distance off the tee.")
        if row["par"] == 5 and par5_leak:
            tips.append("Par 5 — with par-5 scoring as a leak, play for a comfortable 3rd-shot yardage rather than going for the green in 2.")
        if driving_leak and row["par"] != 3:
            tips.append("Consider club-down off the tee here given your current driving accuracy trend.")
        if row.get("hazard_notes"):
            tips.append(f"Hazard note: {row['hazard_notes']}")
        notes.append({
            "Hole": int(row["hole_number"]),
            "Par": int(row["par"]),
            "Yardage": row["yardage"],
            "Strategy": " | ".join(tips) if tips else "Play your normal game plan.",
        })

    return pd.DataFrame(notes)
