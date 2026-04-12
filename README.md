# 🔍 Log Explainer

> Plain-English log analysis for on-call engineers. Powered by a local LLM — no API keys, no data leaving your machine.

[![CI](https://github.com/sharanch/log-explainer/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/log-explainer/actions/workflows/ci.yml)
[![Docker](https://github.com/sharanch/log-explainer/actions/workflows/docker.yml/badge.svg)](https://github.com/YOUR_USERNAME/log-explainer/actions/workflows/docker.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it does

Log Explainer tails a live log file and uses a local LLM (via [Ollama](https://ollama.com)) to explain each line in plain English — in real time. Built for SREs and developers during incident response, when you need to understand what's happening fast.

**Features:**
- 🤖 **Plain-English explanations** — translates cryptic log lines into actionable descriptions
- 🚦 **Severity classification** — auto-tags `INFO / WARN / ERROR / CRITICAL`
- 🔁 **Pattern detection** — alerts when the same error repeats 5+ times in 60 seconds
- 🚨 **Incident summarization** — generates a 2-3 sentence incident summary when error spikes are detected
- 🔒 **Fully local** — runs on Ollama, no API keys, no data sent externally
- 🐳 **Docker + docker-compose** — one command to spin up the full stack

---

## Quick start

### Option 1: Run locally

**Prerequisites:** Python 3.12+, [Ollama](https://ollama.com/download) installed and running.

```bash
# 1. Clone the repo
git clone https://github.com/sharanch/log-explainer.git
cd log-explainer

# 2. Install dependencies
pip install -r requirements.txt

# 3. Pull a model
ollama pull qwen2.5-coder

# 4. Run it
python log_parser.py /var/log/myapp.log
```

### Option 2: Docker Compose (recommended)

Spins up Ollama + Log Explainer together — no local install needed.

```bash
# Set your log file path and run
LOG_FILE_PATH=/var/log/myapp.log docker compose up
```

With options:

```bash
LOG_FILE_PATH=/var/log/myapp.log \
APP_CONTEXT="Django REST API with Postgres and Redis" \
OLLAMA_MODEL=mistral \
MIN_SEVERITY=WARN \
docker compose up
```

### Option 3: Pull from GHCR

```bash
docker pull ghcr.io/sharanch/log-explainer:latest

docker run --rm -it \
  -v /var/log/myapp.log:/logs/app.log:ro \
  --network host \
  ghcr.io/sharanch/log-explainer:latest \
  /logs/app.log --model llama3
```

---

## Usage

```
python log_parser.py <logfile> [options]

Arguments:
  logfile               Path to the log file to tail

Options:
  --model MODEL         Ollama model to use (default: llama3)
  --context CONTEXT     App description to improve explanations
                        e.g. "Django REST API with Postgres"
  --severity LEVEL      Minimum severity to display: INFO, WARN, ERROR, CRITICAL
                        (default: INFO)
```

**Examples:**

```bash
# Basic usage
python log_parser.py /var/log/myapp.log

# Only show warnings and above
python log_parser.py /var/log/myapp.log --severity WARN

# Provide app context for better explanations
python log_parser.py /var/log/myapp.log \
  --context "FastAPI service connecting to MongoDB and RabbitMQ"

# Use a different model
python log_parser.py /var/log/myapp.log --model qwen2.5-coder

# Pipe from another command
tail -f /var/log/myapp.log | python log_parser.py /dev/stdin
```

---

## Example output

```
10:01:05  [WARN    ] Retrying database connection attempt 1
          ↳ The app is having trouble reaching the database and is attempting to reconnect.

10:01:07  [ERROR   ] Connection refused to postgres:5432
          ↳ The app cannot reach the PostgreSQL database — it may be down or the host/port is wrong.

10:01:08  [ERROR   ] Connection refused to postgres:5432
10:01:09  [ERROR   ] Connection refused to postgres:5432
10:01:10  [ERROR   ] Connection refused to postgres:5432
10:01:11  [ERROR   ] Connection refused to postgres:5432
          ⚠ Pattern repeated 5x in 60s — possible recurring issue

🚨 INCIDENT SPIKE DETECTED — generating summary...
The application has lost connectivity to PostgreSQL after exhausting all retry
attempts. This is likely a database crash or network partition. Immediate action:
check PostgreSQL service health and verify network connectivity from the app host.
```

---

## Recommended models

| Model | Size | Best for |
|---|---|---|
| `llama3` | 4.7GB | Best general explanations |
| `mistral` | 4.1GB | Fast, solid quality |
| `qwen2.5-coder` | 4.7GB | Code-heavy / stack traces |
| `phi3` | 2.3GB | Low-resource machines |

Pull any model with: `ollama pull <model-name>`

---

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt ruff pytest pytest-cov

# Run tests
pytest tests/ -v --cov=log_parser

# Lint
ruff check log_parser.py tests/
```

---

## CI/CD

| Workflow | Trigger | What it does |
|---|---|---|
| **CI** | Every push / PR | Lint with `ruff`, run `pytest` with coverage |
| **Docker** | Merge to `main` / version tag | Build image, push to GHCR |

Images are tagged automatically: `latest`, branch name, `sha-<short>`, and semver on tags.

---

## License

MIT
