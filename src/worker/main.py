import os, json, time
import psycopg, boto3
from datetime import datetime
import redis
from uuid import UUID

S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET = os.getenv("S3_BUCKET", "traces")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

r = redis.from_url(REDIS_URL)
s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
)

def ensure_bucket():
    existing = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    if S3_BUCKET not in existing:
        s3.create_bucket(Bucket=S3_BUCKET)

def put_trace_event(trace_id: str, event: dict):
    # append NDJSON line to an object (for MVP: read-modify-write)
    # later could switch to multipart append or object-per-batch and compact daily(?)
    key = f"raw/{trace_id}.ndjson"
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
        body = obj["Body"].read().decode()
    except s3.exceptions.NoSuchKey:
        body = ""
    body += json.dumps(event, separators=(",", ":")) + "\n"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body.encode())

def index_event(event_id: str, trace_id: str, seq: int, ts: str, typ: str):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO events_index(event_id, trace_id, seq, ts, type)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
            """, (event_id, trace_id, seq, ts, typ))
        conn.commit()

def main():
    ensure_bucket()
    last_id = "0-0"
    while True:
        # block for up to 2s for new events
        resp = r.xread({"events": last_id}, block=2000, count=100)
        if not resp:
            continue
        stream, messages = resp[0]
        for msg_id, fields in messages:
            last_id = msg_id.decode()
            trace_id = fields[b"trace_id"].decode()
            event_id = fields[b"event_id"].decode()
            seq = int(fields[b"seq"].decode())
            ts = fields[b"ts"].decode()
            typ = fields[b"type"].decode()
            payload = json.loads(fields[b"payload"].decode())

            event = {
                "trace_id": trace_id,
                "seq": seq,
                "ts": ts,
                "type": typ,
                "payload": payload
            }

            put_trace_event(trace_id, event)
            index_event(event_id, trace_id, seq, ts, typ)

if __name__ == "__main__":
    main()
