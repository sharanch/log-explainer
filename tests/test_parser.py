import io
import json
import time
from unittest.mock import patch, MagicMock
from log_parser import classify_severity, PatternDetector, IncidentSummarizer, explain_log_line


# ── Severity classification ──────────────────────────────────────────────────

class TestClassifySeverity:
    def test_critical(self):
        assert classify_severity("CRITICAL: Out of memory") == "CRITICAL"
        assert classify_severity("FATAL error in thread main") == "CRITICAL"

    def test_error(self):
        assert classify_severity("ERROR: Connection refused") == "ERROR"
        assert classify_severity("Traceback (most recent call last):") == "ERROR"
        assert classify_severity("requests.exceptions.ConnectionError: Failed") == "ERROR"

    def test_warn(self):
        assert classify_severity("WARNING: Deprecated API usage") == "WARN"
        assert classify_severity("Retrying connection attempt 3") == "WARN"

    def test_info(self):
        assert classify_severity("INFO: Server started on port 8000") == "INFO"
        assert classify_severity("Connected to database successfully") == "INFO"

    def test_unknown(self):
        assert classify_severity("some random log line with no markers") == "UNKNOWN"

    def test_case_sensitivity(self):
        # Explicit severity words are matched case-insensitively (upper() pass)
        assert classify_severity("ERROR: something went wrong") == "ERROR"
        assert classify_severity("error: something went wrong") == "ERROR"
        assert classify_severity("Warning: disk almost full") == "WARN"
        # A line with no severity keyword at all should be UNKNOWN
        assert classify_severity("something went wrong") == "UNKNOWN"

    def test_explicit_severity_wins_over_pattern(self):
        # A WARNING line that also contains a pattern keyword (e.g. "lag")
        # should be classified as WARN, not ERROR
        line = "2026-04-12 17:30:06 WARNING  Kafka consumer lag growing: topic=order-events lag=1500"
        assert classify_severity(line) == "WARN"

    def test_explicit_severity_wins_for_full_loadgen_line(self):
        # Full loadgen-style line with timestamp prefix
        line = "2026-04-12 17:30:04,792 WARNING  Auto-vacuum running on table 'orders', may cause slowdown"
        assert classify_severity(line) == "WARN"

    def test_fallback_pattern_for_bare_traceback(self):
        # No explicit severity word — should fall back to pattern matching
        assert classify_severity("Traceback (most recent call last):") == "ERROR"

    def test_fallback_pattern_for_oom(self):
        # OOMKilled has no explicit severity word — pattern match should catch it
        assert classify_severity("OOMKilled: container exceeded memory limit") == "CRITICAL"


# ── Pattern detector ─────────────────────────────────────────────────────────

class TestPatternDetector:
    def test_no_alert_below_threshold(self):
        detector = PatternDetector(window_seconds=60, threshold=5)
        for _ in range(4):
            result = detector.check("ERROR: DB connection failed at 12:00:01")
            assert result is None

    def test_alert_at_threshold(self):
        detector = PatternDetector(window_seconds=60, threshold=5)
        result = None
        for _ in range(5):
            result = detector.check("ERROR: DB connection failed at 12:00:01")
        assert result == 5

    def test_alert_fires_once(self):
        detector = PatternDetector(window_seconds=60, threshold=3)
        alerts = []
        for _ in range(6):
            r = detector.check("ERROR: timeout at 12:00:01")
            if r:
                alerts.append(r)
        assert len(alerts) == 1

    def test_different_lines_tracked_separately(self):
        detector = PatternDetector(window_seconds=60, threshold=3)
        for _ in range(3):
            detector.check("ERROR: DB timeout")
        result = detector.check("ERROR: Auth failed")
        assert result is None

    def test_normalizes_numbers(self):
        detector = PatternDetector(window_seconds=60, threshold=3)
        lines = [
            "ERROR: retry attempt 1 failed",
            "ERROR: retry attempt 2 failed",
            "ERROR: retry attempt 3 failed",
        ]
        result = None
        for line in lines:
            result = detector.check(line)
        assert result == 3

    def test_window_eviction_resets_alert(self):
        detector = PatternDetector(window_seconds=1, threshold=3)
        for _ in range(3):
            detector.check("ERROR: disk full")
        time.sleep(1.1)
        results = []
        for _ in range(3):
            r = detector.check("ERROR: disk full")
            if r:
                results.append(r)
        assert len(results) == 1


# ── Incident summarizer ───────────────────────────────────────────────────────

class TestIncidentSummarizer:
    def test_does_not_summarize_below_threshold(self):
        s = IncidentSummarizer(window_seconds=120, spike_threshold=10)
        for _ in range(9):
            s.record("ERROR: something", "ERROR")
        assert not s.should_summarize()

    def test_summarizes_at_threshold(self):
        s = IncidentSummarizer(window_seconds=120, spike_threshold=5)
        for _ in range(5):
            s.record("ERROR: DB down", "ERROR")
        assert s.should_summarize()

    def test_summary_not_triggered_twice_quickly(self):
        s = IncidentSummarizer(window_seconds=120, spike_threshold=3)
        for _ in range(3):
            s.record("ERROR: crash", "ERROR")
        assert s.should_summarize()
        assert not s.should_summarize()

    def test_ignores_non_errors(self):
        s = IncidentSummarizer(window_seconds=120, spike_threshold=3)
        for _ in range(10):
            s.record("INFO: request received", "INFO")
        assert not s.should_summarize()

    def test_get_summary_prompt_contains_errors(self):
        s = IncidentSummarizer(window_seconds=120, spike_threshold=2)
        s.record("ERROR: DB connection refused", "ERROR")
        s.record("ERROR: DB connection refused", "ERROR")
        prompt = s.get_summary_prompt()
        assert "DB connection refused" in prompt

    def test_deques_stay_in_sync_after_eviction(self):
        s = IncidentSummarizer(window_seconds=1, spike_threshold=99)
        for _ in range(5):
            s.record("ERROR: something", "ERROR")
        time.sleep(1.1)
        s.record("ERROR: new", "ERROR")
        assert len(s.error_times) == len(s.error_lines)
        assert len(s.error_times) == 1


# ── Ollama integration (mocked) ───────────────────────────────────────────────
# explain_log_line now streams and prints directly rather than returning a string.
# Tests capture stdout and verify the printed output.

def _make_stream_response(*tokens: str):
    """Build a mock streaming response from a list of tokens."""
    chunks = [
        json.dumps({"message": {"content": t}, "done": False}).encode()
        for t in tokens
    ]
    # Final chunk signals done
    chunks.append(json.dumps({"message": {"content": ""}, "done": True}).encode())

    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_lines = MagicMock(return_value=iter(chunks))
    return mock_response


class TestExplainLogLine:
    @patch("log_parser.requests.post")
    def test_streams_explanation_to_stdout(self, mock_post, capsys):
        mock_post.return_value = _make_stream_response("The ", "database ", "is down.")
        explain_log_line("ERROR: Connection refused to postgres:5432", "qwen2.5-coder")
        captured = capsys.readouterr()
        assert "The " in captured.out
        assert "database " in captured.out
        assert "is down." in captured.out

    @patch("log_parser.requests.post")
    def test_prints_arrow_prefix(self, mock_post, capsys):
        mock_post.return_value = _make_stream_response("Something failed.")
        explain_log_line("ERROR: something", "qwen2.5-coder")
        captured = capsys.readouterr()
        assert "↳" in captured.out

    @patch("log_parser.requests.post")
    def test_returns_none(self, mock_post):
        mock_post.return_value = _make_stream_response("ok")
        result = explain_log_line("ERROR: something", "qwen2.5-coder")
        assert result is None

    @patch("log_parser.requests.post")
    def test_handles_connection_error(self, mock_post, capsys):
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError()
        explain_log_line("ERROR: something", "qwen2.5-coder")
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out

    @patch("log_parser.requests.post")
    def test_handles_timeout(self, mock_post, capsys):
        import requests as req
        mock_post.side_effect = req.exceptions.Timeout()
        explain_log_line("ERROR: something", "qwen2.5-coder")
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out
        assert "timed out" in captured.out.lower()

    @patch("log_parser.requests.post")
    def test_handles_generic_exception(self, mock_post, capsys):
        mock_post.side_effect = Exception("unexpected failure")
        explain_log_line("ERROR: something", "qwen2.5-coder")
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out

    def test_empty_line_prints_nothing(self, capsys):
        explain_log_line("   ", "qwen2.5-coder")
        captured = capsys.readouterr()
        assert captured.out == ""