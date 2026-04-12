# Log Explainer — Runbook

> Plain-English log analysis for on-call engineers. Powered by a local LLM via Ollama — no API keys, no data leaving your machine.

---

## Prerequisites

Ollama must be installed and running, with a model pulled.

```bash
# Start Ollama (keep this tab open)
ollama serve

# Confirm your model is available
ollama list
# Expected: qwen2.5-coder:1.5b (or whichever model you use)

# Pull it if missing
ollama pull qwen2.5-coder:1.5b
```

Python 3.12+ and dependencies must be installed:

```bash
pip install -r requirements.txt
```

---

## Basic Usage

```bash
python3 log_parser.py /path/to/app.log --model qwen2.5-coder:1.5b
```

The tool seeks to EOF on start — it only processes lines written **after** launch. You will see:

```
🔍 Log Explainer — SRE Incident Response Tool
File:     /path/to/app.log
Model:    qwen2.5-coder:1.5b
Filter:   INFO+
────────────────────────────────────────────────────────────
Waiting for new log lines...
```

---

## You can test the tail using the following 

```bash
 nohup python3 scripts/loadgen.py --output /tmp/output.log --duration 300 --rate 2 & ssh localhost "tail -f /tmp/output.log" | log-explainer /dev/stdin

```


## Options

| Flag | Default | Description |
|---|---|---|
| `--model` | `qwen2.5-coder:1.5b` | Ollama model to use |
| `--context` | _(empty)_ | App description — improves explanation quality |
| `--severity` | `INFO` | Minimum severity to display: `INFO`, `WARN`, `ERROR`, `CRITICAL` |
nohup
---

## Common Invocations

```bash
# Cut noise during an incident — only warnings and above
python3 log_parser.py /var/log/myapp.log \
  --model qwen2.5-coder:1.5b \
  --severity WARN

# Provide app context for better explanations
python3 log_parser.py /var/log/myapp.log \
  --model qwen2.5-coder:1.5b \
  --context "FastAPI service with PostgreSQL and Redis" \
  --severity WARN

# Pipe mode — when you can't point at a file directly
tail -f /var/log/syslog | python3 log_parser.py /dev/stdin \
  --model qwen2.5-coder:1.5b
```

---

## Automatic Alerts

No configuration needed — these fire on their own.

**Pattern spike** — fires when the same error pattern repeats 5+ times in 60 seconds:

```
⚠ Pattern repeated 5x in 60s — possible recurring issue
```

**Incident summary** — fires when 10+ errors accumulate in 120 seconds. Calls the LLM to summarize what is likely going wrong and suggest one immediate action:

```
🚨 INCIDENT SPIKE DETECTED — generating summary...
```

---

## Docker / Docker Compose

```bash
# Copy env file and set your log path (must be absolute)
cp .env.example .env
# Edit .env: set LOG_FILE_PATH=/absolute/path/to/your/app.log

# Start the stack
docker compose up
```

Inline with overrides:

```bash
LOG_FILE_PATH=/var/log/myapp.log \
APP_CONTEXT="Django REST API with Postgres and Redis" \
OLLAMA_MODEL=qwen2.5-coder:1.5b \
MIN_SEVERITY=WARN \
docker compose up
```

Pull and run directly from GHCR:

```bash
docker pull ghcr.io/sharanch/log-explainer:latest

docker run --rm -it \
  -v /var/log/myapp.log:/logs/app.log:ro \
  --network host \
  ghcr.io/sharanch/log-explainer:latest \
  /logs/app.log --model qwen2.5-coder:1.5b
```

---

## Verifying It Works

In a second terminal, append a test line to your log file:

```bash
echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR Connection refused to postgres:5432" >> /path/to/app.log
```

You should see the line appear with a severity tag and an LLM explanation within a few seconds.

---

## Troubleshooting

**`[ERROR] Cannot connect to Ollama`**
Ollama is not running. Start it with `ollama serve` and keep the tab open.

**`[ERROR] 404 Client Error`**
The model name does not match what is pulled. Run `ollama list` to check the exact tag and pass it via `--model`.

**`[ERROR] Ollama timed out`**
The model is still loading on first use. Wait 10–15 seconds and try again. Subsequent calls will be faster.

**Tool exits immediately with no output**
The log file does not exist at the path given. Double-check the path.

**Existing log lines are being processed on startup**
You are pointing at a file that is being actively written to at the moment of launch, or the file was recently modified. The tool seeks to EOF on start — only lines written after launch are processed. This is expected behavior.

**Docker: log file not found inside container**
`LOG_FILE_PATH` must be an absolute path. Relative paths silently fail with bind mounts. Check your `.env` file.

---

## Recommended Models

| Model | Size | Notes |
|---|---|---|
| `qwen2.5-coder:1.5b` | 1GB | Default — fast, low memory |
| `qwen2.5-coder` | 4.7GB | Better quality for code/stack traces |
| `mistral` | 4.1GB | Fast, solid general quality |
| `llama3` | 4.7GB | Best general explanations |
| `phi3` | 2.3GB | Good for low-resource machines |

Pull any model with: `ollama pull <model-name>`