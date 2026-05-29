import gzip
import json
import os
from datetime import datetime

DATA_FOLDER = "data"
OUTPUT_FOLDER = "output"

def load_events(filepath):
    events = []
    with gzip.open(filepath, 'rt', encoding='utf-8') as f:
        for line in f:
            events.append(json.loads(line.strip()))
    return events

def extract_schema(events, sample_size=500):
    """
    Walk through sample_size events and build a schema:
    field_path -> {types seen, null count, present count}
    """
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

    # convert sets to lists for JSON serialization
    for path in schema:
        schema[path]["types"] = list(schema[path]["types"])
        null_rate = schema[path]["null_count"] / sample_size * 100
        schema[path]["null_rate_pct"] = round(null_rate, 1)

    return schema

def compare_schemas(schema_a, schema_b, name_a, name_b):
    """Compare two schemas and return a drift report"""
    fields_a = set(schema_a.keys())
    fields_b = set(schema_b.keys())

    drifts = []

    # fields in A but missing from B
    for field in fields_a - fields_b:
        drifts.append({
            "type": "FIELD_DISAPPEARED",
            "field": field,
            "detail": f"Present in {name_a} but missing from {name_b}"
        })

    # fields in B but missing from A
    for field in fields_b - fields_a:
        drifts.append({
            "type": "NEW_FIELD_APPEARED",
            "field": field,
            "detail": f"New field in {name_b} not seen in {name_a}"
        })

    # fields in both — check for type changes and null rate spikes
    for field in fields_a & fields_b:
        types_a = set(schema_a[field]["types"])
        types_b = set(schema_b[field]["types"])

        if types_a != types_b:
            drifts.append({
                "type": "TYPE_CHANGED",
                "field": field,
                "detail": f"Types changed from {types_a} to {types_b}"
            })

        null_a = schema_a[field]["null_rate_pct"]
        null_b = schema_b[field]["null_rate_pct"]
        if abs(null_b - null_a) > 10:
            drifts.append({
                "type": "NULL_RATE_SPIKE",
                "field": field,
                "detail": f"Null rate changed from {null_a}% to {null_b}%"
            })

    return drifts

def print_drift_report(all_drifts):
    print("\n" + "="*55)
    print(" SCHEMA DRIFT REPORT")
    print("="*55)

    if not any(drifts for _, drifts in all_drifts):
        print(" No schema drift detected across all files.")
    else:
        for comparison, drifts in all_drifts:
            if drifts:
                print(f"\n Comparing: {comparison}")
                for d in drifts:
                    print(f"   [{d['type']}] {d['field']}")
                    print(f"   -> {d['detail']}")

    print("\n" + "="*55)
    print(" SCHEMA SUMMARY (fields seen across all files)")
    print("="*55)

def simulate_drift(events):
    """
    Inject artificial drift into a copy of events
    to prove the detector works
    """
    import copy
    import random
    random.seed(42)

    drifted = []
    for e in events[:500]:
        e2 = copy.deepcopy(e)

        # simulate: 'public' field disappears
        if "public" in e2:
            del e2["public"]

        # simulate: new field 'api_version' appears
        e2["api_version"] = "v4"

        # simulate: null rate spike on actor.login
        if random.random() < 0.4:
            e2["actor"]["login"] = None

        drifted.append(e2)

    return drifted

if __name__ == "__main__":
    files = sorted([f for f in os.listdir(DATA_FOLDER) if f.endswith(".json.gz")])
    print(f"Found {len(files)} files: {files}")

    # build schema for each real file
    schemas = {}
    for f in files:
        path = os.path.join(DATA_FOLDER, f)
        print(f"Building schema for {f}...")
        events = load_events(path)
        schemas[f] = extract_schema(events, sample_size=500)
        print(f"  -> {len(schemas[f])} fields mapped")

    # compare real files against each other
    file_list = list(schemas.keys())
    all_drifts = []
    for i in range(len(file_list) - 1):
        name_a = file_list[i]
        name_b = file_list[i + 1]
        drifts = compare_schemas(schemas[name_a], schemas[name_b], name_a, name_b)
        all_drifts.append((f"{name_a} vs {name_b}", drifts))

    print_drift_report(all_drifts)

    # now simulate drift and prove detector catches it
    print("\n" + "="*55)
    print(" DRIFT SIMULATION TEST")
    print("="*55)
    print("Simulating 3 drift types on file 1:")
    print("  1. 'public' field disappears")
    print("  2. new field 'api_version' appears")
    print("  3. actor.login null rate spikes to ~40%")

    baseline_events = load_events(os.path.join(DATA_FOLDER, files[0]))
    drifted_events = simulate_drift(baseline_events)

    baseline_schema = extract_schema(baseline_events, sample_size=500)
    drifted_schema = extract_schema(drifted_events, sample_size=500)

    sim_drifts = compare_schemas(baseline_schema, drifted_schema,
                                  "baseline", "drifted_version")

    print(f"\n Drift types injected : 3")
    print(f" Drift types caught   : {len(sim_drifts)}")
    print(f" Catch rate           : {len(sim_drifts)/3*100:.0f}%")
    print("\n Detected drifts:")
    for d in sim_drifts:
        print(f"   [{d['type']}] {d['field']}")
        print(f"   -> {d['detail']}")

    # save changelog
    changelog = {
        "generated_at": datetime.now().isoformat(),
        "real_file_comparisons": [
            {"comparison": c, "drifts": d} for c, d in all_drifts
        ],
        "simulation_result": {
            "injected": 3,
            "caught": len(sim_drifts),
            "catch_rate_pct": round(len(sim_drifts)/3*100, 1),
            "drifts": sim_drifts
        }
    }
    output_path = os.path.join(OUTPUT_FOLDER, "drift_changelog.json")
    with open(output_path, 'w') as f:
        json.dump(changelog, f, indent=2)
    print(f"\n Changelog saved to {output_path}")