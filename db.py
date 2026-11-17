"""db.py - saves content plans in a local SQLite file (planner.db)."""

import json
import sqlite3
from datetime import datetime

DB_PATH = "planner.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS plans (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   created TEXT NOT NULL,
                   topic TEXT NOT NULL,
                   audience TEXT NOT NULL,
                   platform TEXT NOT NULL,
                   tone TEXT NOT NULL,
                   status TEXT NOT NULL,
                   payload TEXT NOT NULL
               )"""
        )


def save_plan(inputs, posts, status="approved"):
    """Store a plan. `posts` is the (possibly human-edited) list of post dicts."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO plans (created, topic, audience, platform, tone, status, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                inputs["topic"],
                inputs["audience"],
                inputs["platform"],
                inputs["tone"],
                status,
                json.dumps(posts),
            ),
        )
        return cur.lastrowid


def list_plans():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created, topic, platform, tone, status FROM plans ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_plan(plan_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        return None
    plan = dict(row)
    plan["posts"] = json.loads(plan.pop("payload"))
    return plan
