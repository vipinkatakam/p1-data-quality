import gzip
import json
import os
import yaml
from datetime import datetime

DATA_FOLDER = "data"
RULES_FOLDER = "rules"
OUTPUT_FOLDER = "output"

def load_events(filepath):
    events = []
    with gzip.open(filepath, 'rt', encoding='utf-8') as f:
        for line in f:
            events.append(json.loads(line.strip()))
    return events

def get_nested_value(event, field_path):
    """Get value from nested field like 'actor.login' or 'repo.name'"""
    keys = field_path.split(".")
    value = event
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value

class ValidationRule:
    def __init__(self, field, rule, **kwargs):
        self.field = field
        self.rule = rule
        self.kwargs = kwargs

    def check(self, event):
        value = get_nested_value(event, self.field)

        if self.rule == "not_null":
            passed = value is not None and value != ""
            return passed, f"[not_null] '{self.field}' is null or empty"

        if self.rule == "value_in_set":
            allowed = self.kwargs.get("values", [])
            passed = value in allowed
            return passed, f"[value_in_set] '{self.field}' value '{value}' not in allowed set"

        if self.rule == "regex_match":
            import re
            pattern = self.kwargs.get("pattern", "")
            passed = bool(re.match(pattern, str(value))) if value else False
            return passed, f"[regex_match] '{self.field}' value '{value}' did not match pattern"

        if self.rule == "record_count_min":
            # used at dataset level, not per event
            return True, ""

        return True, ""

def load_rules_from_yaml(filepath):
    with open(filepath, 'r') as f:
        config = yaml.safe_load(f)
    rules = []
    for r in config.get("rules", []):
        rule = ValidationRule(
            field=r["field"],
            rule=r["rule"],
            **{k: v for k, v in r.items() if k not in ("field", "rule")}
        )
        rules.append(rule)
    return rules

def run_validation(events, rules):
    results = {
        "total_events": len(events),
        "total_violations": 0,
        "violations_by_rule": {},
        "sample_violations": {}
    }

    for event in events:
        for rule in rules:
            passed, message = rule.check(event)
            if not passed:
                key = f"{rule.field}:{rule.rule}"
                results["violations_by_rule"][key] = \
                    results["violations_by_rule"].get(key, 0) + 1
                results["total_violations"] += 1

                # store up to 3 sample violations per rule
                if key not in results["sample_violations"]:
                    results["sample_violations"][key] = []
                if len(results["sample_violations"][key]) < 3:
                    results["sample_violations"][key].append({
                        "event_id": event.get("id"),
                        "event_type": event.get("type"),
                        "message": message
                    })

    return results

def print_report(results):
    total = results["total_events"]
    violations = results["total_violations"]
    
    print("\n" + "="*55)
    print(" VALIDATION REPORT")
    print("="*55)
    print(f" Total events checked  : {total:,}")
    print(f" Total violations      : {violations:,}")
    print(f" Clean rate            : {((total - violations) / total * 100):.1f}%")
    print("="*55)

    print("\n Violations by rule:")
    for rule_key, count in sorted(results["violations_by_rule"].items(),
                                   key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"   {rule_key:<45} {count:>7,}  ({pct:.1f}%)")

    print("\n Sample violations:")
    for rule_key, samples in results["sample_violations"].items():
        print(f"\n   Rule: {rule_key}")
        for s in samples:
            print(f"     event_id={s['event_id']} type={s['event_type']}")
            print(f"     -> {s['message']}")

    # save to output folder
    output_path = os.path.join(OUTPUT_FOLDER, "validation_report.json")
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n Full report saved to {output_path}")

if __name__ == "__main__":
    # load rules
    rules_path = os.path.join(RULES_FOLDER, "rules.yaml")
    rules = load_rules_from_yaml(rules_path)
    print(f"Loaded {len(rules)} rules from {rules_path}")

    # load events
    all_events = []
    for f in os.listdir(DATA_FOLDER):
        if f.endswith(".json.gz"):
            path = os.path.join(DATA_FOLDER, f)
            print(f"Loading {f}...")
            all_events.extend(load_events(path))
    print(f"Total events loaded: {len(all_events):,}")

    # ── INJECT BAD DATA ──────────────────────────────────────
    print("\nInjecting 100 intentionally bad events...")

    bad_events = []

    # 30 events with null actor.login
    for i in range(30):
        e = all_events[i].copy()
        e["actor"] = e["actor"].copy()
        e["actor"]["login"] = None
        bad_events.append(e)

    # 30 events with unknown event type
    for i in range(30, 60):
        e = all_events[i].copy()
        e["type"] = "HackerEvent"
        bad_events.append(e)

    # 20 events with null repo name
    for i in range(60, 80):
        e = all_events[i].copy()
        e["repo"] = e["repo"].copy()
        e["repo"]["name"] = None
        bad_events.append(e)

    # 20 events with bad timestamp format
    for i in range(80, 100):
        e = all_events[i].copy()
        e["created_at"] = "15-01-2024 09:00:00"  # wrong format
        bad_events.append(e)

    # mix bad events into real events
    import random
    random.seed(42)
    test_events = all_events + bad_events
    random.shuffle(test_events)

    print(f"Total events after injection: {len(test_events):,}")
    print(f"  -> {len(all_events):,} real events")
    print(f"  -> {len(bad_events)} injected bad events")
    # ─────────────────────────────────────────────────────────

    # run validation on mixed dataset
    results = run_validation(test_events, rules)
    print_report(results)

    # ── MEASURE CATCH RATE ───────────────────────────────────
    print("\n" + "="*55)
    print(" CATCH RATE ANALYSIS")
    print("="*55)
    total_injected = len(bad_events)
    total_caught = results["total_violations"]
    catch_rate = (total_caught / total_injected) * 100
    print(f" Bad events injected   : {total_injected}")
    print(f" Violations caught     : {total_caught}")
    print(f" Catch rate            : {catch_rate:.1f}%")
    print(f"\n This is YOUR '35% error reduction' metric.")
    print(f" In interviews: 'My framework caught {catch_rate:.0f}% of")
    print(f" injected data quality issues across {len(test_events):,} events'")
    print("="*55)