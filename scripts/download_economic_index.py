"""Download the Anthropic Economic Index from HuggingFace and save as JSON lookup.

Uses labor_market_impacts/job_exposure.csv which contains:
  occ_code          — SOC occupation code (6-digit, no dot)
  title             — occupation name
  observed_exposure — fraction of tasks where AI is already being used (0–1)
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

OUTPUT = Path(__file__).parent.parent / "data" / "economic_index.json"

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

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT, "w") as f:
    json.dump(lookup, f, indent=2)

print(f"Saved {len(lookup)} records to {OUTPUT}")
print(f"Exposure range: {df['observed_exposure'].min():.3f} – {df['observed_exposure'].max():.3f}")
