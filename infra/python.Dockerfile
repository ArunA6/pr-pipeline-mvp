FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /app/
RUN pip install --upgrade pip && pip install --no-cache-dir .
COPY src /app/src
COPY tests /app/tests
ENV PYTHONUNBUFFERED=1
