# Data

This folder contains raw GitHub Archive event files (.json.gz).
Files are excluded from the repo due to size (100MB+ each).

## How to download

Run these commands from the project root:

```bash
curl -o data/2024-01-15-9.json.gz https://data.gharchive.org/2024-01-15-9.json.gz
curl -o data/2024-01-15-10.json.gz https://data.gharchive.org/2024-01-15-10.json.gz
curl -o data/2024-01-15-11.json.gz https://data.gharchive.org/2024-01-15-11.json.gz
```

## Source

https://www.gharchive.org — free public GitHub event archive.
Each file covers one hour of all public GitHub activity.