import argparse
import gzip
import json
import os
import yaml
import re
from datetime import datetime

from validator     import load_events, load_rules_from_yaml, run_validation, print_report
from drift_detector import extract_schema, compare_schemas
from reconciler    import process_events, reconcile, print_reconciliation_report
from visualizer    import (plot_validation_summary,
                           plot_reconciliation_summary,
                           plot_pipeline_health)

DATA_FOLDER    = "data"
RULES_FOLDER   = "rules"
OUTPUT_FOLDER  = "output"
BASELINE_FILE  = os.path.join(OUTPUT_FOLDER, "baseline_schema.json")

def run_full_pipeline(filepath):
    filename = os.path.basename(filepath)
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "="*55)
    print(f"  FULL PIPELINE RUN  [{ts}]")
    print(f"  File: {filename}")
    print("="*55)

    # ── STEP 1: LOAD ──────────────────────────
    print("\n[1/4] Loading events...")
    events = load_events(filepath)
    print(f"      Loaded {len(events):,} events")

    # ── STEP 2: VALIDATE ──────────────────────
    print("\n[2/4] Running validation...")
    rules      = load_rules_from_yaml(os.path.join(RULES_FOLDER, "rules.yaml"))
    validation = run_validation(events, rules)
    print_report(validation)

    # ── STEP 3: SCHEMA DRIFT ──────────────────
    print("\n[3/4] Checking schema drift...")
    current_schema = extract_schema(events)
    drifts         = []

    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE) as f:
            baseline = json.load(f)
        drifts = compare_schemas(baseline, current_schema)
        if drifts:
            print(f"      ✗ {len(drifts)} drift(s) detected")
            for d in drifts:
                print(f"        [{d['type']}] {d['field']} — {d['detail']}")
        else:
            print("      ✓ No schema drift detected")
    else:
        print("      No baseline found — saving current schema as baseline")

    with open(BASELINE_FILE, 'w') as f:
        json.dump(current_schema, f, indent=2)

    # ── STEP 4: RECONCILE ─────────────────────
    print("\n[4/4] Running reconciliation...")
    processed, dropped = process_events(events)
    recon              = reconcile(events, processed, dropped, filename)
    print_reconciliation_report(recon)

    # ── SAVE REPORTS ──────────────────────────
    print("\nSaving reports...")
    val_path = os.path.join(OUTPUT_FOLDER, "validation_report.json")
    with open(val_path, 'w') as f:
        json.dump(validation, f, indent=2)

    recon_output = {"generated_at": datetime.now().isoformat(),
                    "tests": [recon]}
    recon_path   = os.path.join(OUTPUT_FOLDER, "reconciliation_report.json")
    with open(recon_path, 'w') as f:
        json.dump(recon_output, f, indent=2)

    # ── CHARTS ────────────────────────────────
    print("\nGenerating charts...")
    plot_validation_summary(validation)
    plot_reconciliation_summary(recon_output)
    plot_pipeline_health(validation, recon_output)

    # ── FINAL SUMMARY ─────────────────────────
    print("\n" + "="*55)
    print("  PIPELINE COMPLETE")
    print("="*55)
    v_status = "✓ PASSED" if validation["total_violations"] == 0 else \
               f"✗ {validation['total_violations']} violations"
    d_status = "✓ CLEAN"  if not drifts else f"✗ {len(drifts)} drifts"
    r_status = "✓ PASSED" if recon["status"] == "PASSED" else "✗ FAILED"

    print(f"  Validation   : {v_status}")
    print(f"  Schema drift : {d_status}")
    print(f"  Reconcile    : {r_status}")
    print(f"  Reports      : {OUTPUT_FOLDER}/")
    print(f"  Charts       : {OUTPUT_FOLDER}/*.png")
    print("="*55)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Data Quality Pipeline — Project 1")

    parser.add_argument(
        "--file",
        help="Path to a single .json.gz file to process",
        default=None)

    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all .json.gz files in data/ folder")

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run validation only, skip reconciliation and charts")

    args = parser.parse_args()

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    if args.file:
        run_full_pipeline(args.file)

    elif args.all:
        files = sorted([f for f in os.listdir(DATA_FOLDER)
                        if f.endswith(".json.gz")])
        print(f"Found {len(files)} files to process")
        for f in files:
            run_full_pipeline(os.path.join(DATA_FOLDER, f))

    elif args.validate_only:
        files = sorted([f for f in os.listdir(DATA_FOLDER)
                        if f.endswith(".json.gz")])
        for f in files:
            path   = os.path.join(DATA_FOLDER, f)
            events = load_events(path)
            rules  = load_rules_from_yaml(
                         os.path.join(RULES_FOLDER, "rules.yaml"))
            result = run_validation(events, rules)
            print_report(result)

    else:
        print("Usage:")
        print("  python main.py --file data/2024-01-15-9.json.gz")
        print("  python main.py --all")
        print("  python main.py --validate-only")