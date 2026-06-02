import gzip
import json
import os
import time
import yaml
import re
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

DATA_FOLDER   = "data"
RULES_FOLDER  = "rules"
OUTPUT_FOLDER = "output"
BASELINE_FILE = os.path.join(OUTPUT_FOLDER, "baseline_schema.json")

# ─────────────────────────────────────────────
#  CORE HELPERS  (same logic as before)
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

def load_rules_from_yaml(filepath):
    with open(filepath, 'r') as f:
        config = yaml.safe_load(f)
    return config.get("rules", [])

def run_validation(events, rules):
    violations = {}
    total = 0
    for event in events:
        for rule in rules:
            field   = rule["field"]
            rtype   = rule["rule"]
            value   = get_nested_value(event, field)
            passed  = True
            message = ""

            if rtype == "not_null":
                passed  = value is not None and value != ""
                message = f"[not_null] '{field}' is null or empty"

            elif rtype == "value_in_set":
                passed  = value in rule.get("values", [])
                message = f"[value_in_set] '{field}' got '{value}'"

            elif rtype == "regex_match":
                pattern = rule.get("pattern", "")
                passed  = bool(re.match(pattern, str(value))) if value else False
                message = f"[regex_match] '{field}' got '{value}'"

            if not passed:
                key = f"{field}:{rtype}"
                violations[key] = violations.get(key, 0) + 1
                total += 1

    return {"total_events": len(events), "total_violations": total,
            "violations_by_rule": violations}

def extract_schema(events, sample_size=500):
    schema = {}

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{prefix}.{key}" if prefix else key
                if path not in schema:
                    schema[path] = {"types": set(), "null_count": 0, "present_count": 0}
                if value is None:
                    schema[path]["null_count"] += 1
                else:
                    schema[path]["types"].add(type(value).__name__)
                schema[path]["present_count"] += 1
                if isinstance(value, dict):
                    walk(value, path)

    for event in events[:sample_size]:
        walk(event)

    result = {}
    for path, info in schema.items():
        result[path] = {
            "types": list(info["types"]),
            "null_rate_pct": round(info["null_count"] / sample_size * 100, 1)
        }
    return result

def compare_schemas(baseline, current):
    drifts = []
    fields_b = set(baseline.keys())
    fields_c = set(current.keys())

    for f in fields_b - fields_c:
        drifts.append({"type": "FIELD_DISAPPEARED", "field": f,
                        "detail": "Present in baseline, missing now"})
    for f in fields_c - fields_b:
        drifts.append({"type": "NEW_FIELD_APPEARED", "field": f,
                        "detail": "New field not in baseline"})
    for f in fields_b & fields_c:
        if set(baseline[f]["types"]) != set(current[f]["types"]):
            drifts.append({"type": "TYPE_CHANGED", "field": f,
                            "detail": f"Was {baseline[f]['types']} now {current[f]['types']}"})
        nb = baseline[f]["null_rate_pct"]
        nc = current[f]["null_rate_pct"]
        if abs(nc - nb) > 10:
            drifts.append({"type": "NULL_RATE_SPIKE", "field": f,
                            "detail": f"Null rate {nb}% → {nc}%"})
    return drifts

# ─────────────────────────────────────────────
#  ALERT  (terminal + HTML report)
# ─────────────────────────────────────────────

def send_terminal_alert(filename, validation, drifts):
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "─" * 55

    print(f"\n{'═'*55}")
    print(f"  PIPELINE ALERT  [{ts}]")
    print(f"{'═'*55}")
    print(f"  File      : {filename}")
    print(f"  Events    : {validation['total_events']:,}")
    print(sep)

    # validation result
    v = validation['total_violations']
    if v == 0:
        print("  VALIDATION  ✓  No violations found")
    else:
        print(f"  VALIDATION  ✗  {v} violations detected")
        for rule_key, count in validation['violations_by_rule'].items():
            print(f"    • {rule_key:<42} {count:>6,}")

    print(sep)

    # drift result
    if not drifts:
        print("  SCHEMA      ✓  No drift detected")
    else:
        print(f"  SCHEMA      ✗  {len(drifts)} drift(s) detected")
        for d in drifts:
            print(f"    • [{d['type']}] {d['field']}")
            print(f"      → {d['detail']}")

    print(f"{'═'*55}\n")

def save_html_report(filename, validation, drifts):
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    v_ok    = validation['total_violations'] == 0
    d_ok    = len(drifts) == 0
    v_color = "#16a34a" if v_ok else "#dc2626"
    d_color = "#16a34a" if d_ok else "#dc2626"
    v_label = "PASSED" if v_ok else "FAILED"
    d_label = "CLEAN"  if d_ok else "DRIFTED"

    violation_rows = ""
    for rule_key, count in validation['violations_by_rule'].items():
        violation_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;
                     font-family:monospace;font-size:13px;">{rule_key}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;
                     text-align:right;color:#dc2626;font-weight:600;">{count:,}</td>
        </tr>"""

    drift_rows = ""
    for d in drifts:
        drift_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;
                     font-family:monospace;font-size:12px;color:#7c3aed;">
                     [{d['type']}]</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;
                     font-family:monospace;font-size:13px;">{d['field']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;
                     font-size:13px;color:#6b7280;">{d['detail']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Pipeline Report — {filename}</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#f9fafb;margin:0;padding:32px;color:#111;}}
    .card{{background:#fff;border-radius:12px;border:1px solid #e5e7eb;
           padding:24px;margin-bottom:20px;max-width:860px;}}
    .badge{{display:inline-block;padding:4px 12px;border-radius:99px;
            font-size:12px;font-weight:600;color:#fff;}}
    table{{width:100%;border-collapse:collapse;}}
    th{{text-align:left;padding:8px 12px;font-size:12px;
        text-transform:uppercase;letter-spacing:.05em;
        color:#6b7280;border-bottom:2px solid #e5e7eb;}}
    h2{{font-size:15px;font-weight:600;margin:0 0 16px;}}
    .meta{{font-size:13px;color:#6b7280;margin-bottom:6px;}}
  </style>
</head>
<body>
  <div style="max-width:860px">
    <h1 style="font-size:22px;margin-bottom:4px;">Pipeline Quality Report</h1>
    <p style="color:#6b7280;font-size:14px;margin-bottom:24px;">
      Generated {ts}</p>

    <div class="card">
      <div class="meta">File processed</div>
      <div style="font-family:monospace;font-size:15px;
                  font-weight:600;margin-bottom:16px;">{filename}</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;">
        <div style="background:#f3f4f6;border-radius:8px;padding:12px 20px;">
          <div style="font-size:11px;color:#6b7280;margin-bottom:4px;">EVENTS</div>
          <div style="font-size:22px;font-weight:700;">
            {validation['total_events']:,}</div>
        </div>
        <div style="background:#f3f4f6;border-radius:8px;padding:12px 20px;">
          <div style="font-size:11px;color:#6b7280;margin-bottom:4px;">VALIDATION</div>
          <div style="font-size:22px;font-weight:700;color:{v_color};">{v_label}</div>
        </div>
        <div style="background:#f3f4f6;border-radius:8px;padding:12px 20px;">
          <div style="font-size:11px;color:#6b7280;margin-bottom:4px;">SCHEMA</div>
          <div style="font-size:22px;font-weight:700;color:{d_color};">{d_label}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Validation results
        <span class="badge" style="background:{v_color};margin-left:8px;">
          {validation['total_violations']:,} violations</span>
      </h2>
      {"<p style='color:#16a34a;font-size:14px;'>All rules passed. No violations found.</p>"
        if v_ok else
        f"<table><thead><tr><th>Rule</th><th style='text-align:right'>Count</th>"
        f"</tr></thead><tbody>{violation_rows}</tbody></table>"}
    </div>

    <div class="card">
      <h2>Schema drift
        <span class="badge" style="background:{d_color};margin-left:8px;">
          {len(drifts)} drift(s)</span>
      </h2>
      {"<p style='color:#16a34a;font-size:14px;'>Schema matches baseline. No drift detected.</p>"
        if d_ok else
        f"<table><thead><tr><th>Type</th><th>Field</th><th>Detail</th>"
        f"</tr></thead><tbody>{drift_rows}</tbody></table>"}
    </div>
  </div>
</body>
</html>"""

    report_name = filename.replace(".json.gz", "") + "_report.html"
    report_path = os.path.join(OUTPUT_FOLDER, report_name)
    with open(report_path, 'w') as f:
        f.write(html)
    print(f"  HTML report saved → {report_path}")
    return report_path

# ─────────────────────────────────────────────
#  PIPELINE  (runs on every new file)
# ─────────────────────────────────────────────

def run_pipeline(filepath):
    filename = os.path.basename(filepath)
    print(f"\n[PIPELINE] New file detected: {filename}")

    # 1. load events
    print(f"[PIPELINE] Loading events...")
    events = load_events(filepath)

    # 2. run validation
    print(f"[PIPELINE] Running validation...")
    rules      = load_rules_from_yaml(os.path.join(RULES_FOLDER, "rules.yaml"))
    validation = run_validation(events, rules)

    # 3. schema drift check
    print(f"[PIPELINE] Checking schema drift...")
    current_schema = extract_schema(events)
    drifts = []

    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE, 'r') as f:
            baseline_schema = json.load(f)
        drifts = compare_schemas(baseline_schema, current_schema)
    else:
        # first file ever — save as baseline
        print(f"[PIPELINE] No baseline found — saving this file as baseline.")
        with open(BASELINE_FILE, 'w') as f:
            json.dump(current_schema, f, indent=2)

    # 4. fire alerts
    send_terminal_alert(filename, validation, drifts)
    save_html_report(filename, validation, drifts)

    # 5. update baseline to latest schema
    with open(BASELINE_FILE, 'w') as f:
        json.dump(current_schema, f, indent=2)
    print(f"[PIPELINE] Baseline updated.")

# ─────────────────────────────────────────────
#  FILE WATCHER  (the "Lambda trigger")
# ─────────────────────────────────────────────

class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".json.gz"):
            time.sleep(5)  # wait for file to finish writing
            run_pipeline(event.src_path)

if __name__ == "__main__":
    print("="*55)
    print("  DATA QUALITY PIPELINE — WATCHING FOR NEW FILES")
    print(f"  Monitoring folder: {os.path.abspath(DATA_FOLDER)}")
    print("  Drop any .json.gz file into data/ to trigger")
    print("  Press Ctrl+C to stop")
    print("="*55)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    observer = Observer()
    observer.schedule(NewFileHandler(), DATA_FOLDER, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[PIPELINE] Stopped.")
    observer.join()