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
        assert classify_severity("error: something went wrong") == "UNKNOWN"  # lowercase not matched
        assert classify_severity("ERROR: something went wrong") == "ERROR"


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
        assert not s.should_summarize()  # second call should be blocked

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


# ── Ollama integration (mocked) ───────────────────────────────────────────────

class TestExplainLogLine:
    @patch("log_parser.requests.post")
    def test_returns_explanation(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "The database connection was refused."}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = explain_log_line("ERROR: Connection refused to postgres:5432", "qwen2.5-coder")
        assert result == "The database connection was refused."

    @patch("log_parser.requests.post", side_effect=Exception("Connection error"))
    def test_handles_connection_error(self, mock_post):
        result = explain_log_line("ERROR: something", "qwen2.5-coder")
        assert "[ERROR]" in result

    def test_empty_line_returns_empty(self):
        result = explain_log_line("   ", "qwen2.5-coder")
        assert result == ""
