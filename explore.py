import gzip
import json
import os

DATA_FOLDER = "data"

def load_events(filepath):
    events = []
    with gzip.open(filepath, 'rt', encoding='utf-8') as f:
        for line in f:
            events.append(json.loads(line.strip()))
    return events

def profile_events(events):
    print(f"\n Total events loaded: {len(events)}")
    
    # show all unique event types
    event_types = {}
    for e in events:
        t = e.get("type", "unknown")
        event_types[t] = event_types.get(t, 0) + 1
    
    print("\n Event types found:")
    for k, v in sorted(event_types.items(), key=lambda x: -x[1]):
        print(f"   {k:<30} {v:>6} events")
    
    # show all top-level fields
    all_keys = set()
    for e in events[:100]:
        all_keys.update(e.keys())
    
    print(f"\n Top-level fields in the data:")
    for key in sorted(all_keys):
        print(f"   {key}")
    
    # show one full event as example
    print("\n Example event (first PushEvent):")
    for e in events:
        if e.get("type") == "PushEvent":
            print(json.dumps(e, indent=2)[:800])
            break

if __name__ == "__main__":
    files = [f for f in os.listdir(DATA_FOLDER) if f.endswith(".json.gz")]
    print(f"Found {len(files)} files: {files}")
    
    all_events = []
    for f in files:
        path = os.path.join(DATA_FOLDER, f)
        print(f"Loading {f}...")
        events = load_events(path)
        all_events.extend(events)
        print(f"  -> {len(events)} events")
    
    profile_events(all_events)