from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any
from uuid import uuid4, UUID
from datetime import datetime, timezone
import os, json, hashlib
import redis
import psycopg
from src.common.db import ensure_schema

r = redis.from_url(os.getenv("REDIS_URL"))
DATABASE_URL = os.getenv("DATABASE_URL")

def create_app():
    app = FastAPI(title="PR Telemetry Ingestion API")
    ensure_schema()

    class Event(BaseModel):
        seq: int
        ts: datetime
        type: Literal["edit", "command", "test", "commit", "annotation"]
        payload: Dict[str, Any] = Field(default_factory=dict)

    class Batch(BaseModel):
        trace_id: UUID | None = None
        pr_id: str
        repo_name: str
        branch: str
        status: Literal["open","merged","closed"] = "open"
        events: List[Event]

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/ingest")
    def ingest(batch: Batch):
        trace_id = batch.trace_id or uuid4()
        # basic index upsert for traces
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO traces(trace_id, pr_id, repo_name, branch, status)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (trace_id) DO UPDATE SET status=excluded.status
                """, (str(trace_id), batch.pr_id, batch.repo_name, batch.branch, batch.status))
            conn.commit()

        accepted = []
        pipe = r.pipeline()
        for ev in batch.events:
            # event_id = sha256(trace_id|seq|type|payload)
            h = hashlib.sha256()
            h.update(str(trace_id).encode())
            h.update(str(ev.seq).encode())
            h.update(ev.type.encode())
            h.update(json.dumps(ev.payload, sort_keys=True).encode())
            event_id = h.hexdigest()
            key = f"event:{event_id}"
            if not r.exists(key):
                # store raw event to a Redis stream for worker
                pipe.xadd("events", {"trace_id": str(trace_id),
                                     "event_id": event_id,
                                     "seq": ev.seq,
                                     "ts": ev.ts.replace(tzinfo=timezone.utc).isoformat(),
                                     "type": ev.type,
                                     "payload": json.dumps(ev.payload)})
                pipe.set(key, 1, ex=86400)  # idempotency guard (1 day TTL)
                accepted.append(event_id)
        pipe.execute()

        return {"trace_id": str(trace_id), "accepted_event_ids": accepted}

    return app
