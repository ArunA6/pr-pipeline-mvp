import psycopg
import os

DATABASE_URL = os.getenv("DATABASE_URL")

DDL = """
CREATE TABLE IF NOT EXISTS traces (
  trace_id UUID PRIMARY KEY,
  pr_id TEXT NOT NULL,
  repo_name TEXT NOT NULL,
  branch TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS events_index (
  event_id TEXT PRIMARY KEY,
  trace_id UUID NOT NULL,
  seq INT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  type TEXT NOT NULL
);
"""

def ensure_schema():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
