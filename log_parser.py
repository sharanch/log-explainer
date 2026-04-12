#!/usr/bin/env python3

import sys
import time
import argparse
import requests
import re
from datetime import datetime
from collections import deque

import os

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = "qwen2.5-coder"

SYSTEM_PROMPT_TEMPLATE = """You are an expert SRE and application log analyst{context_clause}.
Explain log lines in plain English for an on-call engineer during an incident.
Be concise — 1 to 2 sentences max.
Focus on: what happened, why it might have occurred, and if it looks like an error, what to check next.
Never repeat the raw log line. Just explain it clearly."""

SEVERITY_PATTERNS = {
    "CRITICAL": [r"\bCRITICAL\b", r"\bFATAL\b", r"\bPANIC\b", r"OutOfMemory", r"OOMKilled", r"segfault"],
    "ERROR":    [r"\bERROR\b", r"\bException\b", r"\bTraceback\b", r"\bFailed\b", r"\bfailed\b", r"500"],
    "WARN":     [r"\bWARN\b", r"\bWARNING\b", r"\bDeprecated\b", r"\bRetrying\b", r"\bretry\b", r"timeout"],
    "INFO":     [r"\bINFO\b", r"\bStarted\b", r"\bStopped\b", r"\bConnected\b", r"\bListening\b"],
}

SEVERITY_COLORS = {
    "CRITICAL": "\033[1;35m",  # bold magenta
    "ERROR":    "\033[1;31m",  # bold red
    "WARN":     "\033[1;33m",  # bold yellow
    "INFO":     "\033[1;34m",  # bold blue
    "UNKNOWN":  "\033[0;37m",  # grey
}
RESET = "\033[0m"
DIM   = "\033[2m"
BOLD  = "\033[1m"


def classify_severity(line: str) -> str:
    for severity, patterns in SEVERITY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, line):
                return severity
    return "UNKNOWN"


def explain_log_line(line: str, model: str, context: str = "") -> str:
    line = line.strip()
    if not line:
        return ""

    context_clause = f" familiar with {context} applications" if context else ""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context_clause=context_clause)

    payload = {
        "model": model,
        "prompt": f"Explain this application log line in plain English:\n\n{line}",
        "system": system_prompt,
        "stream": False,
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return "[ERROR] Cannot connect to Ollama. Is it running? Try: ollama serve"
    except requests.exceptions.Timeout:
        return "[ERROR] Ollama timed out. Model may still be loading."
    except Exception as e:
        return f"[ERROR] {str(e)}"


class PatternDetector:
    """Detects repeated error patterns within a sliding time window."""

    def __init__(self, window_seconds: int = 60, threshold: int = 5):
        self.window_seconds = window_seconds
        self.threshold = threshold
        self.buckets: dict[str, deque] = {}
        self.alerted: set[str] = set()

    def _normalize(self, line: str) -> str:
        # Strip timestamps, IDs, and numbers to find structural patterns
        line = re.sub(r"\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}[\.,]?\d*", "", line)
        line = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", line)
        line = re.sub(r"\b\d+\b", "<n>", line)
        return line.strip()

    def check(self, line: str) -> int | None:
        """Returns count if threshold crossed, else None."""
        key = self._normalize(line)
        now = time.time()

        if key not in self.buckets:
            self.buckets[key] = deque()

        dq = self.buckets[key]
        dq.append(now)

        # Evict old entries outside the window
        while dq and dq[0] < now - self.window_seconds:
            dq.popleft()

        count = len(dq)
        if count >= self.threshold and key not in self.alerted:
            self.alerted.add(key)
            return count

        # Reset alert if count drops back below threshold
        if count < self.threshold and key in self.alerted:
            self.alerted.discard(key)

        return None


class IncidentSummarizer:
    """Tracks recent errors and produces incident summaries."""

    def __init__(self, window_seconds: int = 120, spike_threshold: int = 10):
        self.window_seconds = window_seconds
        self.spike_threshold = spike_threshold
        self.error_times: deque = deque()
        self.error_lines: deque = deque()
        self.last_summary_at: float = 0

    def record(self, line: str, severity: str):
        if severity in ("ERROR", "CRITICAL"):
            now = time.time()
            self.error_times.append(now)
            self.error_lines.append(line.strip())

            # Evict old
            while self.error_times and self.error_times[0] < now - self.window_seconds:
                self.error_times.popleft()
                if self.error_lines:
                    self.error_lines.popleft()

    def should_summarize(self) -> bool:
        now = time.time()
        if (len(self.error_times) >= self.spike_threshold and
                now - self.last_summary_at > self.window_seconds):
            self.last_summary_at = now
            return True
        return False

    def get_summary_prompt(self) -> str:
        lines = list(self.error_lines)[-20:]
        joined = "\n".join(lines)
        return (
            f"You are an SRE. The following {len(self.error_times)} errors occurred in the last "
            f"{self.window_seconds} seconds. Summarize what is likely going wrong in 2-3 sentences "
            f"and suggest one immediate action.\n\nErrors:\n{joined}"
        )


def print_separator():
    print(f"{DIM}{'─' * 60}{RESET}")


def tail_file(filepath: str, model: str, context: str, min_severity: str):
    severity_order = ["INFO", "UNKNOWN", "WARN", "ERROR", "CRITICAL"]
    min_index = severity_order.index(min_severity) if min_severity in severity_order else 0

    detector = PatternDetector(window_seconds=60, threshold=5)
    summarizer = IncidentSummarizer(window_seconds=120, spike_threshold=10)

    print(f"\n{BOLD}🔍 Log Explainer{RESET} — SRE Incident Response Tool")
    print(f"{DIM}File:     {filepath}{RESET}")
    print(f"{DIM}Model:    {model}{RESET}")
    print(f"{DIM}Filter:   {min_severity}+{RESET}")
    if context:
        print(f"{DIM}Context:  {context}{RESET}")
    print_separator()
    print(f"{DIM}Waiting for new log lines...{RESET}\n")

    try:
        with open(filepath, "r") as f:
            f.seek(0, 2)  # seek to end

            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.3)
                    continue

                line = line.strip()
                if not line:
                    continue

                severity = classify_severity(line)
                summarizer.record(line, severity)

                # Filter by minimum severity
                if severity_order.index(severity) < min_index:
                    continue

                color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["UNKNOWN"])
                ts = datetime.now().strftime("%H:%M:%S")

                print(f"{DIM}{ts}{RESET} {color}[{severity:<8}]{RESET} {line}")

                # Pattern spike detection
                repeat_count = detector.check(line)
                if repeat_count:
                    print(f"  {SEVERITY_COLORS['WARN']}⚠ Pattern repeated {repeat_count}x in 60s — possible recurring issue{RESET}")

                # Explain the line
                explanation = explain_log_line(line, model, context)
                if explanation:
                    print(f"  {DIM}↳{RESET} {explanation}")

                # Incident summary on error spikes
                if summarizer.should_summarize():
                    print()
                    print(f"{SEVERITY_COLORS['CRITICAL']}{BOLD}🚨 INCIDENT SPIKE DETECTED — generating summary...{RESET}")
                    summary = explain_log_line(summarizer.get_summary_prompt(), model, context)
                    print(f"{BOLD}{summary}{RESET}")
                    print_separator()

                print()

    except FileNotFoundError:
        print(f"[ERROR] File not found: {filepath}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{DIM}[Stopped]{RESET}")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Tail a log file and explain each line in plain English using a local Ollama model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python log_parser.py /var/log/myapp.log
  python log_parser.py /var/log/myapp.log --model mistral
  python log_parser.py /var/log/myapp.log --context "Django REST API" --severity WARN
  tail -f /var/log/myapp.log | python log_parser.py /dev/stdin
        """
    )
    parser.add_argument("logfile", help="Path to the log file to tail")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--context", default="", help='App description e.g. "Django REST API with Postgres"')
    parser.add_argument(
        "--severity", default="INFO",
        choices=["INFO", "WARN", "ERROR", "CRITICAL"],
        help="Minimum severity to display (default: INFO)"
    )

    args = parser.parse_args()
    tail_file(args.logfile, args.model, args.context, args.severity)


if __name__ == "__main__":
    main()
