import gzip
import json
import os
import yaml
import re
from datetime import datetime

DATA_FOLDER   = "data"
RULES_FOLDER  = "rules"
OUTPUT_FOLDER = "output"

THRESHOLD_PCT = 1.0  # alert if more than 1% records lost

# ─────────────────────────────────────────────
#  LOAD
# ─────────────────────────────────────────────

def load_events(filepath):
    events = []
    with gzip.open(filepath, 'rt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events

def get_nested_value(event, field_path):
    keys = field_path.split(".")
    value = event
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value

# ─────────────────────────────────────────────
#  SIMULATE PROCESSING  (what a real pipeline does)
# ─────────────────────────────────────────────

def process_events(events):
    """
    Simulates what your ETL pipeline does:
    - filter to only PushEvents and PullRequestEvents
    - extract key fields into clean flat records
    - drop records with missing critical fields
    Returns processed records + a processing log
    """
    processed   = []
    dropped_log = []

    for event in events:
        event_type = event.get("type")

        # only keep these two event types
        if event_type not in ("PushEvent", "PullRequestEvent"):
            continue

        actor_login = get_nested_value(event, "actor.login")
        repo_name   = get_nested_value(event, "repo.name")
        created_at  = event.get("created_at")

        # drop records missing critical fields
        if not actor_login:
            dropped_log.append({
                "event_id": event.get("id"),
                "reason": "missing actor.login"
            })
            continue

        if not repo_name:
            dropped_log.append({
                "event_id": event.get("id"),
                "reason": "missing repo.name"
            })
            continue

        if not created_at:
            dropped_log.append({
                "event_id": event.get("id"),
                "reason": "missing created_at"
            })
            continue

        # clean flat record — what lands in your database
        processed.append({
            "event_id":   event.get("id"),
            "type":       event_type,
            "actor":      actor_login,
            "repo":       repo_name,
            "created_at": created_at
        })

    return processed, dropped_log

# ─────────────────────────────────────────────
#  RECONCILIATION ENGINE
# ─────────────────────────────────────────────

def reconcile(source_events, processed_records, dropped_log, filename):
    """
    Compares counts at every stage of the pipeline.
    Flags if loss exceeds threshold.
    """

    # count at each stage
    source_count    = len(source_events)
    relevant_count  = sum(1 for e in source_events
                         if e.get("type") in ("PushEvent", "PullRequestEvent"))
    processed_count = len(processed_records)
    dropped_count   = len(dropped_log)

    # what we expect vs what we got
    expected  = relevant_count
    actual    = processed_count
    lost      = expected - actual
    lost_pct  = (lost / expected * 100) if expected > 0 else 0

    # duplicate check — event_id should be unique
    ids         = [r["event_id"] for r in processed_records]
    unique_ids  = set(ids)
    duplicates  = len(ids) - len(unique_ids)

    # build result
    status = "PASSED"
    alerts = []

    if lost_pct > THRESHOLD_PCT:
        status = "FAILED"
        alerts.append(
            f"Record loss {lost_pct:.2f}% exceeds threshold of {THRESHOLD_PCT}%"
        )

    if duplicates > 0:
        status = "FAILED"
        alerts.append(f"{duplicates:,} duplicate event IDs detected")

    result = {
        "filename":        filename,
        "timestamp":       datetime.now().isoformat(),
        "status":          status,
        "threshold_pct":   THRESHOLD_PCT,
        "counts": {
            "source_total":    source_count,
            "relevant":        relevant_count,
            "processed":       processed_count,
            "dropped":         dropped_count,
            "lost":            lost,
            "lost_pct":        round(lost_pct, 4),
            "duplicates":      duplicates
        },
        "alerts":          alerts,
        "dropped_sample":  dropped_log[:5]
    }

    return result

# ─────────────────────────────────────────────
#  PRINT REPORT
# ─────────────────────────────────────────────

def print_reconciliation_report(result):
    c      = result["counts"]
    status = result["status"]
    color  = "✓" if status == "PASSED" else "✗"

    print("\n" + "="*55)
    print(f"  RECONCILIATION REPORT  [{color} {status}]")
    print("="*55)
    print(f"  File         : {result['filename']}")
    print(f"  Threshold    : >{result['threshold_pct']}% loss triggers alert")
    print("─"*55)
    print(f"  Source total : {c['source_total']:>10,}  (all event types)")
    print(f"  Relevant     : {c['relevant']:>10,}  (Push + PR events only)")
    print(f"  Processed    : {c['processed']:>10,}  (landed in database)")
    print(f"  Dropped      : {c['dropped']:>10,}  (missing critical fields)")
    print("─"*55)
    print(f"  Lost         : {c['lost']:>10,}  ({c['lost_pct']:.4f}%)")
    print(f"  Duplicates   : {c['duplicates']:>10,}")
    print("─"*55)

    if result["alerts"]:
        print("\n  ALERTS:")
        for a in result["alerts"]:
            print(f"    ✗ {a}")
    else:
        print("\n  All checks passed. Data integrity confirmed.")

    if result["dropped_sample"]:
        print("\n  Sample dropped records:")
        for d in result["dropped_sample"]:
            print(f"    event_id={d['event_id']}  reason={d['reason']}")

    print("="*55)

# ─────────────────────────────────────────────
#  SIMULATE FAILURES  (prove it works)
# ─────────────────────────────────────────────

def simulate_record_loss(processed_records, loss_pct=5.0):
    """Randomly drop loss_pct% of records to simulate pipeline failure"""
    import random
    random.seed(42)
    keep = int(len(processed_records) * (1 - loss_pct / 100))
    return random.sample(processed_records, keep)

def simulate_duplicates(processed_records, dupe_count=50):
    """Inject duplicate records"""
    import random
    random.seed(99)
    dupes = random.sample(processed_records, dupe_count)
    return processed_records + dupes

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":

    # pick one file to reconcile
    files = sorted([f for f in os.listdir(DATA_FOLDER)
                    if f.endswith(".json.gz")])
    filepath = os.path.join(DATA_FOLDER, files[0])
    filename = files[0]

    print(f"\nLoading {filename}...")
    events = load_events(filepath)
    print(f"Source events loaded: {len(events):,}")

    # process events (simulate ETL pipeline)
    print("Processing events through pipeline...")
    processed, dropped_log = process_events(events)
    print(f"Processed records  : {len(processed):,}")
    print(f"Dropped records    : {len(dropped_log):,}")

    # ── TEST 1: clean run ──────────────────────
    print("\n" + "─"*55)
    print("TEST 1 — Normal pipeline run (expect PASSED)")
    result = reconcile(events, processed, dropped_log, filename)
    print_reconciliation_report(result)

    # ── TEST 2: simulate 5% record loss ───────
    print("\n" + "─"*55)
    print("TEST 2 — Simulate 5% record loss (expect FAILED)")
    lost_records = simulate_record_loss(processed, loss_pct=5.0)
    result2 = reconcile(events, lost_records, dropped_log, filename)
    print_reconciliation_report(result2)

    # ── TEST 3: simulate duplicates ───────────
    print("\n" + "─"*55)
    print("TEST 3 — Simulate 50 duplicate records (expect FAILED)")
    duped_records = simulate_duplicates(processed, dupe_count=50)
    result3 = reconcile(events, duped_records, dropped_log, filename)
    print_reconciliation_report(result3)

    # ── SUMMARY ───────────────────────────────
    print("\n" + "="*55)
    print("  RECONCILIATION TEST SUMMARY")
    print("="*55)
    for label, r in [
        ("Normal run    ", result),
        ("5% loss       ", result2),
        ("50 duplicates ", result3)
    ]:
        icon = "✓" if r["status"] == "PASSED" else "✗"
        print(f"  {label}  [{icon} {r['status']}]")
    print("="*55)

    # save to output
    output = {
        "generated_at": datetime.now().isoformat(),
        "tests": [result, result2, result3]
    }
    path = os.path.join(OUTPUT_FOLDER, "reconciliation_report.json")
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n  Report saved → {path}")