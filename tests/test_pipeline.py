import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validator      import run_validation, ValidationRule
from drift_detector import extract_schema, compare_schemas
from reconciler     import process_events, reconcile

# ─────────────────────────────────────────────
#  SAMPLE DATA  (no files needed)
# ─────────────────────────────────────────────

def make_event(overrides={}):
    """Returns a valid GitHub event, with optional overrides"""
    event = {
        "id":         "123456",
        "type":       "PushEvent",
        "actor":      {"login": "vipin", "id": 1},
        "repo":       {"name": "vipin/test-repo", "id": 999},
        "created_at": "2024-01-15T09:00:00Z",
        "public":     True
    }
    event.update(overrides)
    return event

def make_ruleset():
    return [
        ValidationRule("id",           "not_null"),
        ValidationRule("type",         "not_null"),
        ValidationRule("actor.login",  "not_null"),
        ValidationRule("repo.name",    "not_null"),
        ValidationRule("created_at",   "not_null"),
        ValidationRule("type",         "value_in_set",
                       values=["PushEvent", "PullRequestEvent", "CreateEvent"]),
        ValidationRule("created_at",   "regex_match",
                       pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    ]
# ─────────────────────────────────────────────
#  VALIDATION TESTS
# ─────────────────────────────────────────────

class TestValidation:

    def test_clean_event_passes(self):
        events = [make_event()]
        result = run_validation(events, make_ruleset())
        assert result["total_violations"] == 0

    def test_null_actor_login_caught(self):
        events = [make_event({"actor": {"login": None}})]
        result = run_validation(events, make_ruleset())
        assert result["violations_by_rule"].get("actor.login:not_null", 0) == 1

    def test_unknown_event_type_caught(self):
        events = [make_event({"type": "HackerEvent"})]
        result = run_validation(events, make_ruleset())
        assert result["violations_by_rule"].get("type:value_in_set", 0) == 1

    def test_bad_timestamp_caught(self):
        events = [make_event({"created_at": "15-01-2024 bad format"})]
        result = run_validation(events, make_ruleset())
        assert result["violations_by_rule"].get("created_at:regex_match", 0) == 1

    def test_null_repo_name_caught(self):
        events = [make_event({"repo": {"name": None}})]
        result = run_validation(events, make_ruleset())
        assert result["violations_by_rule"].get("repo.name:not_null", 0) == 1

    def test_multiple_bad_events_all_caught(self):
        events = [
            make_event({"actor": {"login": None}}),
            make_event({"type": "HackerEvent"}),
            make_event({"repo": {"name": None}}),
        ]
        result = run_validation(events, make_ruleset())
        assert result["total_violations"] == 3

    def test_100_clean_events(self):
        events = [make_event() for _ in range(100)]
        result = run_validation(events, make_ruleset())
        assert result["total_violations"] == 0
        assert result["total_events"] == 100

# ─────────────────────────────────────────────
#  SCHEMA DRIFT TESTS
# ─────────────────────────────────────────────

class TestSchemaDrift:

    def test_identical_schemas_no_drift(self):
        events = [make_event() for _ in range(10)]
        schema = extract_schema(events, sample_size=10)
        drifts = compare_schemas(schema, schema, "baseline", "current")
        assert len(drifts) == 0

    def test_missing_field_detected(self):
        baseline_events = [make_event() for _ in range(10)]
        drifted_events  = []
        for e in baseline_events:
            e2 = e.copy()
            del e2["public"]
            drifted_events.append(e2)

        baseline = extract_schema(baseline_events, sample_size=10)
        drifted  = extract_schema(drifted_events,  sample_size=10)
        drifts   = compare_schemas(baseline, drifted, "baseline", "drifted")

        types = [d["type"] for d in drifts]
        assert "FIELD_DISAPPEARED" in types

    def test_new_field_detected(self):
        baseline_events = [make_event() for _ in range(10)]
        drifted_events  = []
        for e in baseline_events:
            e2 = e.copy()
            e2["new_field"] = "surprise"
            drifted_events.append(e2)

        baseline = extract_schema(baseline_events, sample_size=10)
        drifted  = extract_schema(drifted_events,  sample_size=10)
        drifts   = compare_schemas(baseline, drifted, "baseline", "drifted")
        types = [d["type"] for d in drifts]
        assert "NEW_FIELD_APPEARED" in types

# ─────────────────────────────────────────────
#  RECONCILIATION TESTS
# ─────────────────────────────────────────────

class TestReconciliation:

    def make_events(self, count=100):
        return [make_event({"id": str(i)}) for i in range(count)]

    def test_clean_pipeline_passes(self):
        events             = self.make_events(100)
        processed, dropped = process_events(events)
        result             = reconcile(events, processed, dropped, "test.json.gz")
        assert result["status"] == "PASSED"

    def test_record_loss_detected(self):
        events             = self.make_events(100)
        processed, dropped = process_events(events)
        # drop 10% of processed records
        trimmed            = processed[:int(len(processed) * 0.90)]
        result             = reconcile(events, trimmed, dropped, "test.json.gz")
        assert result["status"] == "FAILED"
        assert any("loss" in a.lower() for a in result["alerts"])

    def test_duplicates_detected(self):
        events             = self.make_events(100)
        processed, dropped = process_events(events)
        # inject 10 duplicate records
        duped              = processed + processed[:10]
        result             = reconcile(events, duped, dropped, "test.json.gz")
        assert result["status"] == "FAILED"
        assert any("duplicate" in a.lower() for a in result["alerts"])

    def test_zero_events_handled(self):
        result = reconcile([], [], [], "empty.json.gz")
        assert result["counts"]["source_total"] == 0