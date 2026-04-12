#!/usr/bin/env python3
"""
loadgen.py — Log load generator for testing log-explainer.

Appends realistic log lines to a file for a given duration,
with weighted severity distribution.

Usage:
  python3 loadgen.py                          # append to sample.log for 5s
  python3 loadgen.py --output /tmp/test.log   # custom output file
  python3 loadgen.py --duration 30            # run for 30 seconds
  python3 loadgen.py --rate 5                 # 5 lines per second
"""

import argparse
import random
import time
from datetime import datetime

# ── Log line pool (100 entries) ───────────────────────────────────────────────
# Each entry is (severity, message)

LOG_LINES = [
    # INFO (40 entries)
    ("INFO",     "Starting application on port 8000"),
    ("INFO",     "Connected to PostgreSQL at postgres:5432"),
    ("INFO",     "Redis cache initialized successfully"),
    ("INFO",     "Worker pool started with 4 threads"),
    ("INFO",     "GET /api/users 200 OK (45ms)"),
    ("INFO",     "POST /api/orders 201 Created (112ms)"),
    ("INFO",     "GET /api/products 200 OK (23ms)"),
    ("INFO",     "PUT /api/users/42 200 OK (67ms)"),
    ("INFO",     "DELETE /api/sessions/8821 200 OK (18ms)"),
    ("INFO",     "Scheduled job 'cleanup_expired_tokens' started"),
    ("INFO",     "Scheduled job 'cleanup_expired_tokens' completed in 340ms"),
    ("INFO",     "Cache hit ratio: 87.4% over last 60s"),
    ("INFO",     "Database connection pool size: 10/20"),
    ("INFO",     "Listening on 0.0.0.0:8000"),
    ("INFO",     "Health check passed: all systems nominal"),
    ("INFO",     "Config reloaded from /etc/app/config.yaml"),
    ("INFO",     "TLS certificate valid, expires in 87 days"),
    ("INFO",     "New user registered: user_id=10482"),
    ("INFO",     "Session created for user_id=10482, ttl=3600s"),
    ("INFO",     "Metrics exported to Prometheus endpoint /metrics"),
    ("INFO",     "Graceful shutdown initiated, draining connections"),
    ("INFO",     "Background task 'send_digest_emails' queued"),
    ("INFO",     "S3 upload completed: reports/2026-04-12.csv (2.3MB)"),
    ("INFO",     "Kafka consumer group 'order-events' rebalanced, partitions=3"),
    ("INFO",     "Feature flag 'new_checkout_flow' enabled for 10% of traffic"),
    ("INFO",     "Rate limiter reset for IP 203.0.113.42"),
    ("INFO",     "Audit log written: admin user_id=1 deleted user_id=304"),
    ("INFO",     "gRPC server started on port 50051"),
    ("INFO",     "Dependency check passed: postgres=14.5, redis=7.0.5"),
    ("INFO",     "Request tracing enabled, trace_id=7f3a9c21b4e0"),
    ("INFO",     "CDN cache purged for path /static/app.js"),
    ("INFO",     "OAuth token refreshed for service account svc-worker"),
    ("INFO",     "Compaction triggered on table 'events' (2.1GB freed)"),
    ("INFO",     "Websocket connection established, client_id=ws-8821"),
    ("INFO",     "Batch job processed 1200 records in 4.2s"),
    ("INFO",     "Replica lag is 0ms, replication healthy"),
    ("INFO",     "Circuit breaker for payment-service is CLOSED"),
    ("INFO",     "Auto-scaling: added 1 worker node, total=5"),
    ("INFO",     "Log rotation completed, archived to /var/log/app/2026-04-11.gz"),
    ("INFO",     "Startup complete, ready to serve traffic"),

    # WARN (30 entries)
    ("WARNING",  "Retrying database connection attempt 1 of 5"),
    ("WARNING",  "Retrying database connection attempt 2 of 5"),
    ("WARNING",  "Response time degraded: GET /api/reports took 2300ms"),
    ("WARNING",  "Memory usage at 78%, approaching threshold"),
    ("WARNING",  "Deprecated API endpoint /v1/users called by client 10.0.0.5"),
    ("WARNING",  "Redis cache miss rate exceeded 30% in last 60s"),
    ("WARNING",  "Disk usage at 82% on /var/data, consider cleanup"),
    ("WARNING",  "JWT token expiring soon for user_id=204, issuing refresh"),
    ("WARNING",  "Rate limit approaching for IP 198.51.100.7: 95/100 requests"),
    ("WARNING",  "Kafka consumer lag growing: topic=order-events lag=1500"),
    ("WARNING",  "Slow query detected: SELECT * FROM events took 4100ms"),
    ("WARNING",  "Connection pool saturation: 19/20 connections in use"),
    ("WARNING",  "TLS certificate expires in 14 days, renewal required"),
    ("WARNING",  "Retry attempt 1 for HTTP POST to payment-service"),
    ("WARNING",  "Retry attempt 2 for HTTP POST to payment-service"),
    ("WARNING",  "Background worker queue depth: 850 jobs pending"),
    ("WARNING",  "Config value 'MAX_UPLOAD_SIZE' not set, using default 10MB"),
    ("WARNING",  "Health check latency elevated: postgres responded in 850ms"),
    ("WARNING",  "Graceful shutdown timeout exceeded, forcing exit"),
    ("WARNING",  "S3 upload retrying due to transient error (attempt 2/3)"),
    ("WARNING",  "Feature flag service unreachable, falling back to defaults"),
    ("WARNING",  "CPU usage spike to 91% on worker-3"),
    ("WARNING",  "Replica lag increased to 250ms, monitoring"),
    ("WARNING",  "Circuit breaker for inventory-service is HALF-OPEN"),
    ("WARNING",  "Auto-vacuum running on table 'orders', may cause slowdown"),
    ("WARNING",  "Timeout waiting for lock on resource 'user:8821'"),
    ("WARNING",  "Websocket client ws-4421 disconnected unexpectedly"),
    ("WARNING",  "DNS resolution for cache.internal took 900ms"),
    ("WARNING",  "OpenTelemetry exporter dropped 12 spans due to buffer overflow"),
    ("WARNING",  "Rollout paused: error rate above 2% threshold"),

    # ERROR (20 entries)
    ("ERROR",    "Connection refused to postgres:5432"),
    ("ERROR",    "Traceback (most recent call last): File 'db.py' line 42 in connect"),
    ("ERROR",    "psycopg2.OperationalError: could not connect to server"),
    ("ERROR",    "HTTP 500 Internal Server Error on POST /api/checkout"),
    ("ERROR",    "Failed to publish event to Kafka: topic=order-events"),
    ("ERROR",    "Redis SETNX failed: timeout after 5000ms"),
    ("ERROR",    "Unhandled exception in worker thread: ZeroDivisionError"),
    ("ERROR",    "S3 upload failed after 3 retries: AccessDenied"),
    ("ERROR",    "Payment service returned 503: Service Unavailable"),
    ("ERROR",    "Database transaction rolled back: deadlock detected"),
    ("ERROR",    "JWT verification failed: signature mismatch for user_id=8801"),
    ("ERROR",    "Failed to acquire connection from pool after 10s"),
    ("ERROR",    "gRPC call to inventory-service failed: UNAVAILABLE"),
    ("ERROR",    "Config file /etc/app/config.yaml not found, cannot reload"),
    ("ERROR",    "Batch job 'send_digest_emails' failed: SMTP connection refused"),
    ("ERROR",    "Disk write error on /var/data: No space left on device"),
    ("ERROR",    "Failed to parse request body: invalid JSON"),
    ("ERROR",    "Websocket write error for client ws-8821: broken pipe"),
    ("ERROR",    "Elasticsearch index 'logs-2026' is read-only: disk watermark exceeded"),
    ("ERROR",    "Circuit breaker for payment-service OPENED after 5 consecutive failures"),

    # CRITICAL (10 entries)
    ("CRITICAL", "FATAL: max connection retries exhausted, shutting down"),
    ("CRITICAL", "OOMKilled: process exceeded memory limit of 512MB"),
    ("CRITICAL", "PANIC: nil pointer dereference in handler.go:84"),
    ("CRITICAL", "segfault at address 0x00000000, core dumped"),
    ("CRITICAL", "FATAL: WAL log corrupted, database cannot start"),
    ("CRITICAL", "OutOfMemory: JVM heap space exhausted, killing process"),
    ("CRITICAL", "FATAL: SSL certificate validation failed, refusing to start"),
    ("CRITICAL", "Data loss detected: replication stream broken for 120s"),
    ("CRITICAL", "FATAL: etcd cluster quorum lost, all writes rejected"),
    ("CRITICAL", "Kernel OOM killer terminated PID 8821 (app-worker)"),
]

# ── Severity weights (must sum to 100) ───────────────────────────────────────
# Mirrors realistic production log distribution
SEVERITY_WEIGHTS = {
    "INFO":     40,
    "WARNING":  30,
    "ERROR":    20,
    "CRITICAL": 10,
}

# Pre-bucket lines by severity for fast weighted sampling
_BUCKETS = {}
for sev, weight in SEVERITY_WEIGHTS.items():
    _BUCKETS[sev] = [msg for s, msg in LOG_LINES if s == sev]

_POPULATION = list(SEVERITY_WEIGHTS.keys())
_WEIGHTS     = list(SEVERITY_WEIGHTS.values())


def pick_line() -> tuple[str, str]:
    severity = random.choices(_POPULATION, weights=_WEIGHTS, k=1)[0]
    message  = random.choice(_BUCKETS[severity])
    return severity, message


def write_line(f, severity: str, message: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    line = f"{ts} {severity:<8} {message}\n"
    f.write(line)
    f.flush()
    print(line, end="")


def main():
    parser = argparse.ArgumentParser(
        description="Append realistic log lines to a file for testing log-explainer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 loadgen.py
  python3 loadgen.py --output /tmp/test.log --duration 30
  python3 loadgen.py --rate 10 --duration 60

Then in another terminal:
  python3 log_parser.py sample.log --model qwen2.5-coder:1.5b
        """,
    )
    parser.add_argument("--output",   default="sample.log",  help="Log file to append to (default: sample.log)")
    parser.add_argument("--duration", default=5,   type=int, help="How long to run in seconds (default: 5)")
    parser.add_argument("--rate",     default=2,   type=int, help="Log lines per second (default: 2)")
    args = parser.parse_args()

    interval = 1.0 / args.rate
    end_time = time.time() + args.duration

    print(f"Writing to '{args.output}' for {args.duration}s at {args.rate} lines/sec")
    print(f"Severity weights: {SEVERITY_WEIGHTS}")
    print("─" * 60)

    count = 0
    with open(args.output, "a") as f:
        while time.time() < end_time:
            severity, message = pick_line()
            write_line(f, severity, message)
            count += 1
            time.sleep(interval)

    print("─" * 60)
    print(f"Done. Wrote {count} lines to '{args.output}'.")


if __name__ == "__main__":
    main()
