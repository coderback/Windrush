"""Download the Anthropic Economic Index from HuggingFace and save as JSON lookup.

Uses labor_market_impacts/job_exposure.csv which contains:
  occ_code          — SOC occupation code (6-digit, no dot)
  title             — occupation name
  observed_exposure — fraction of tasks where AI is already being used (0–1)

Also downloads labor_market_impacts/task_penetration.csv which contains:
  task        — natural-language O*NET task description
  penetration — fraction of task done by AI (0–1)
"""
import json
import sys
from pathlib import Path

try:
    from huggingface_hub import hf_hub_download
    import pandas as pd
except ImportError:
    print("Missing deps. Run: pip install huggingface_hub pandas")
    sys.exit(1)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- 1. Job exposure (occupation-level) ---
print("Downloading Anthropic/EconomicIndex — labor_market_impacts/job_exposure.csv ...")
csv_path = hf_hub_download(
    repo_id="Anthropic/EconomicIndex",
    filename="labor_market_impacts/job_exposure.csv",
    repo_type="dataset",
)

df = pd.read_csv(csv_path)
print(f"Loaded {len(df)} rows. Columns: {df.columns.tolist()}")
print(df.head(3).to_string())

lookup = {}
for _, row in df.iterrows():
    code = str(row["occ_code"]).strip()
    lookup[code] = {
        "occupation_name": str(row["title"]).strip(),
        "overall_exposure": float(row["observed_exposure"]) if pd.notna(row["observed_exposure"]) else 0.0,
    }

OUTPUT = DATA_DIR / "economic_index.json"
with open(OUTPUT, "w") as f:
    json.dump(lookup, f, indent=2)

print(f"Saved {len(lookup)} records to {OUTPUT}")
print(f"Exposure range: {df['observed_exposure'].min():.3f} – {df['observed_exposure'].max():.3f}")

# --- 2. Task penetration (task-level NLP signal) ---
print("\nDownloading Anthropic/EconomicIndex — labor_market_impacts/task_penetration.csv ...")
task_csv_path = hf_hub_download(
    repo_id="Anthropic/EconomicIndex",
    filename="labor_market_impacts/task_penetration.csv",
    repo_type="dataset",
)

tp = pd.read_csv(task_csv_path)
print(f"Loaded {len(tp)} rows. Columns: {tp.columns.tolist()}")
print(tp.head(3).to_string())

TASK_OUTPUT = DATA_DIR / "task_penetration.csv"
tp.to_csv(TASK_OUTPUT, index=False)

non_zero = (tp["penetration"] > 0).sum()
print(f"Saved {len(tp)} tasks to {TASK_OUTPUT} ({non_zero} non-zero penetration)")
