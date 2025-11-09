# PLAN

## 1. Clarifying Questions
What is the core “unit” of data (scope of code changes: PR, inter-PR) we want to capture?

Assume that the scope of focus will be per PR data.

How precise and detailed does the event timing need to be?

Assume we don’t need sub-second precision. Capturing the correct order of actions and a timestamp for each event is enough for analysis and replay.

What types of developer activity should we capture?

Assume we can focus on the essential signals:
- Code edits
- Commands
- Commits and pushes
- Test results / CI runs
- Any self-provided notes

How much environment and context do we need to store?

Assume we only need basic metadata

What are the downstream uses and required reliability?

Assume we can abstract/generalize these requirements to focus on general characteristics that appear important for coding efficacy:
- correctness
- completelness
- trace consistency

## 2. Proposed Data Schema
High-level Schema:
```
{
  "trace_id": "uuid",
  "repo": {
    "name": "string",
    "branch": "string",
    "language": ["python", "typescript"]
  },
  "pr": {
    "pr_id": "owner/repo#number",
    "title": "string",
    "status": "open|merged|closed",
    "created_at": "iso8601",
    "merged_at": "iso8601|null"
  },
  "developer": {
    "user_id": "uuid",
    "ide_version": "0.9.2",
    "os": "macOS"
  },
  "timeline": {
    "start_time": "iso8601",
    "end_time": "iso8601",
    "duration_seconds": 1200
  },
  "events": [
    {
      "seq": 1,
      "ts": "iso8601",
      "type": "edit|command|test|commit|annotation",
      "payload": {}
    }
  ]
}
```
Event Type Payloads:
```
{
  "type": "edit",
  "payload": {
    "file": "src/main.py",
    "change_summary": "+25/-10",
    "diff_snippet": "@@ -23,7 +23,10 @@ ..."
  }
}
```

```
{
  "type": "command",
  "payload": {
    "command": "pytest -q",
    "exit_code": 1,
    "stdout_sample": "FAILED test_api.py::test_login"
  }
}
```

```
{
  "type": "commit",
  "payload": {
    "sha": "abc123",
    "message": "fix: handle empty input case",
    "files_changed": 3
  }
}
```

Schema design motivation:
- Simple enough to implement quickly in the IDE and backend
- Fully ordered and queryable by seq
- New event types can be added easily

## 3. High-Level Technical Plan

IDE Telemetry =>  Ingestion API =>  Queue/Processor =>  Storage
                     |                 |                   |
                  FastAPI           Worker             S3 / Postgres

Data Flow:
1. IDE emits events as JSON batches via HTTPS.
2. Ingestion API (FastAPI) validates, timestamps, and assigns sequence numbers.
3. Queue/Worker (Python) processes each batch:
- Orders and groups by PR.
- Normalizes fields and creates the final JSON “PR Trace.”
- Writes the trace to S3 (for storage) and Postgres (for indexing and queries).
4. Query layer (simple read API or SQL) provides trace retrieval and aggregation.

Tech Stack: Python 3, FastAPI, Redis Streams (queue), Postgres database (indexing), S3 bucket storage (MiniO for local?), Pytest testing, Docker Compose Deployment.

Justification: Quick to prorotype and easy to deploy, minimal depedenency, could be scaled later

## 4. Scope & Trade-offs

MVP Scope: 
- Ingest events from IDE to API
- Process and group events into PR traces
- Store traces as JSON files on S3
- Provide a basic endpoint to fetch a PR trace
- Support events: edit, command, commit, test, and annotation

Extensions:
- Fine-grained navigation or cursor events
- Advanced analytics or dashboards
- Full environment snapshotting
- Detailed CI integration and multiple PR linking
- Security and privacy layers

--------------------------------------------------------------

# GUIDE

Follow these steps to run and test the PR Telemetry MVP locally.

## Prerequisites
- Git and Docker and Docker Compose installed locally
- curl or HTTPie for sending test requests

## 1. Clone repo and start the services
```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
docker compose -f infra/docker-compose.yml up --build -d
```

## 2. Post a sample telemetry batch
You can adjust the data in tests/fixutres/sample_batch as desired.
```bash
curl -s localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/sample_batch.json | jq
```

## 3. Validate data retrieved
Postgres:
```bash
docker compose -f infra/docker-compose.yml exec postgres \
  psql -U postgres -d telemetry -c "SELECT * FROM traces;"
docker compose -f infra/docker-compose.yml exec postgres \
  psql -U postgres -d telemetry -c "SELECT COUNT(*) FROM events_index;"
```
The results from here will provide a trace_id you can correlate to an event in MiniO:

MiniO:
- Open http://localhost:9001 ()
- Login: Username = minio, Password = minio12345
- Check event (navigate Buckets => traces => raw => <trace_id>.ndjson)

4. Validate deduplication
Resend same batch:
```bash
curl -s localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/sample_batch.json | jq '.accepted_event_ids | length'
```
The expected results is 0 as duplicates are ignored.
Try this after changed a field (e.g. files_changed from 2 to 3) and re-send, then you should see 1 new event accepted.
