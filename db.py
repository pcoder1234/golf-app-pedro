"""
db.py
Database layer for the Golf Stats app — now backed by Postgres (Supabase)
instead of a local SQLite file, so data persists across app restarts and
redeploys.

Connection string resolution order:
  1. Streamlit secrets (st.secrets["SUPABASE_DB_URL"]) — used when deployed
     on Streamlit Community Cloud, or running locally with a
     .streamlit/secrets.toml file.
  2. Environment variable DATABASE_URL — a fallback for non-Streamlit use.

All function signatures are unchanged from the SQLite version, so
analysis.py and app.py did not need any changes.
"""

import os
from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.extras
import streamlit as st


def _get_connection_string() -> str:
    # Prefer Streamlit secrets (works both locally with secrets.toml and
    # on Streamlit Community Cloud once you've added the secret there).
    try:
        if "SUPABASE_DB_URL" in st.secrets:
            return st.secrets["SUPABASE_DB_URL"]
    except Exception:
        # st.secrets raises if no secrets.toml exists at all locally —
        # fall through to the environment variable check below.
        pass

    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    raise RuntimeError(
        "No database connection string found. Add SUPABASE_DB_URL to "
        ".streamlit/secrets.toml (local) or to your app's Secrets "
        "(Streamlit Community Cloud), or set a DATABASE_URL environment "
        "variable."
    )


@contextmanager
def get_conn():
    conn_str = _get_connection_string()
    conn = psycopg2.connect(conn_str)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS rounds (
                id SERIAL PRIMARY KEY,
                round_date TEXT NOT NULL,
                course_name TEXT NOT NULL,
                tees TEXT,
                course_rating REAL,
                slope_rating REAL,
                weather TEXT,
                notes TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS holes (
                id SERIAL PRIMARY KEY,
                round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
                hole_number INTEGER NOT NULL,
                par INTEGER NOT NULL,
                yardage INTEGER,
                score INTEGER NOT NULL,
                putts INTEGER NOT NULL,
                fairway_hit TEXT,
                gir TEXT,
                penalties INTEGER DEFAULT 0,
                sand_save_attempt TEXT,
                sand_save_success TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS courses (
                id SERIAL PRIMARY KEY,
                course_name TEXT UNIQUE NOT NULL,
                num_holes INTEGER DEFAULT 18
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS course_holes (
                id SERIAL PRIMARY KEY,
                course_name TEXT NOT NULL,
                hole_number INTEGER NOT NULL,
                par INTEGER NOT NULL,
                yardage INTEGER,
                handicap_index INTEGER,
                hazard_notes TEXT,
                UNIQUE(course_name, hole_number)
            )
            """
        )
        cur.close()


def save_round(round_date, course_name, tees, course_rating, slope_rating, weather, notes, holes_df):
    """holes_df: DataFrame with columns matching the holes table (minus id/round_id)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO rounds (round_date, course_name, tees, course_rating, slope_rating, weather, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (str(round_date), course_name, tees, course_rating, slope_rating, weather, notes),
        )
        round_id = cur.fetchone()[0]

        for _, row in holes_df.iterrows():
            cur.execute(
                """
                INSERT INTO holes (
                    round_id, hole_number, par, yardage, score, putts,
                    fairway_hit, gir, penalties, sand_save_attempt, sand_save_success
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    round_id,
                    int(row["hole_number"]),
                    int(row["par"]),
                    int(row["yardage"]) if pd.notna(row["yardage"]) else None,
                    int(row["score"]),
                    int(row["putts"]),
                    row["fairway_hit"],
                    row["gir"],
                    int(row["penalties"]),
                    row.get("sand_save_attempt", "N/A"),
                    row.get("sand_save_success", "N/A"),
                ),
            )
        cur.close()
    return round_id


def get_all_rounds():
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM rounds ORDER BY round_date DESC", conn
        )


def get_holes_for_round(round_id):
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM holes WHERE round_id = %(round_id)s ORDER BY hole_number",
            conn,
            params={"round_id": round_id},
        )


def get_all_holes_joined():
    """All hole-level rows joined with round metadata — the main analysis table."""
    with get_conn() as conn:
        return pd.read_sql_query(
            """
            SELECT h.*, r.round_date, r.course_name, r.tees, r.weather
            FROM holes h
            JOIN rounds r ON h.round_id = r.id
            ORDER BY r.round_date, h.hole_number
            """,
            conn,
        )


def delete_round(round_id):
    with get_conn() as conn:
        cur = conn.cursor()
        # ON DELETE CASCADE on the holes table handles child rows automatically,
        # but deleting explicitly first keeps this safe even if the schema
        # constraint is ever changed.
        cur.execute("DELETE FROM holes WHERE round_id = %s", (round_id,))
        cur.execute("DELETE FROM rounds WHERE id = %s", (round_id,))
        cur.close()


def upsert_course_holes(course_name, holes_df):
    """Save/overwrite a course layout (par, yardage, handicap, hazards) for strategy lookups."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO courses (course_name, num_holes) VALUES (%s, %s) "
            "ON CONFLICT (course_name) DO NOTHING",
            (course_name, len(holes_df)),
        )
        for _, row in holes_df.iterrows():
            cur.execute(
                """
                INSERT INTO course_holes (course_name, hole_number, par, yardage, handicap_index, hazard_notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (course_name, hole_number)
                DO UPDATE SET par = EXCLUDED.par, yardage = EXCLUDED.yardage,
                              handicap_index = EXCLUDED.handicap_index,
                              hazard_notes = EXCLUDED.hazard_notes
                """,
                (
                    course_name,
                    int(row["hole_number"]),
                    int(row["par"]),
                    int(row["yardage"]) if pd.notna(row["yardage"]) else None,
                    int(row["handicap_index"]) if pd.notna(row.get("handicap_index")) else None,
                    row.get("hazard_notes", ""),
                ),
            )
        cur.close()


def get_course_names():
    with get_conn() as conn:
        df = pd.read_sql_query("SELECT DISTINCT course_name FROM courses ORDER BY course_name", conn)
        return df["course_name"].tolist()


def get_course_layout(course_name):
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM course_holes WHERE course_name = %(course_name)s ORDER BY hole_number",
            conn,
            params={"course_name": course_name},
        )