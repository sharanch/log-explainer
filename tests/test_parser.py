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
        # Check every iteration — none should fire before threshold
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
        # After the first alert the key is in self.alerted, so subsequent calls
        # return None until count drops back below threshold and resets.
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
        # Entries older than window_seconds should be evicted, dropping count
        # below threshold and clearing the alert so it can fire again.
        detector = PatternDetector(window_seconds=1, threshold=3)

        # Fire the alert
        for _ in range(3):
            detector.check("ERROR: disk full")

        # Wait for the window to expire
        time.sleep(1.1)

        # Push count back up — should alert again after eviction
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
        assert not s.should_summarize()  # second call within window_seconds should be blocked

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
        # After window expiry, error_times and error_lines must stay the same
        # length — they are always evicted together.
        s = IncidentSummarizer(window_seconds=1, spike_threshold=99)
        for _ in range(5):
            s.record("ERROR: something", "ERROR")

        time.sleep(1.1)

        # Trigger eviction by recording a new entry
        s.record("ERROR: new", "ERROR")

        assert len(s.error_times) == len(s.error_lines)
        assert len(s.error_times) == 1  # only the new entry survives


# ── Ollama integration (mocked) ───────────────────────────────────────────────

class TestExplainLogLine:
    @patch("log_parser.requests.post")
    def test_returns_explanation(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "The database connection was refused."}}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = explain_log_line("ERROR: Connection refused to postgres:5432", "qwen2.5-coder")
        assert result == "The database connection was refused."

    @patch("log_parser.requests.post", side_effect=Exception("Connection error"))
    def test_handles_generic_exception(self, mock_post):
        result = explain_log_line("ERROR: something", "qwen2.5-coder")
        assert "[ERROR]" in result

    @patch("log_parser.requests.post")
    def test_handles_connection_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError()
        result = explain_log_line("ERROR: something", "qwen2.5-coder")
        assert "ollama" in result.lower() or "[ERROR]" in result

    @patch("log_parser.requests.post")
    def test_handles_timeout(self, mock_post):
        import requests as req
        mock_post.side_effect = req.exceptions.Timeout()
        result = explain_log_line("ERROR: something", "qwen2.5-coder")
        assert "timed out" in result.lower() or "[ERROR]" in result

    def test_empty_line_returns_empty(self):
        result = explain_log_line("   ", "qwen2.5-coder")
        assert result == ""
