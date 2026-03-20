"""Download the Anthropic Economic Index from HuggingFace and save as JSON lookup."""
import json
import sys
from pathlib import Path

try:
    from datasets import load_dataset
    import pandas as pd
except ImportError:
    print("Missing deps. Run: pip install datasets pandas")
    sys.exit(1)

OUTPUT = Path(__file__).parent.parent / "data" / "economic_index.json"

print("Loading dataset from HuggingFace (Anthropic/EconomicIndex)...")
dataset = load_dataset("Anthropic/EconomicIndex", split="train")
df = dataset.to_pandas()

print("Columns:", df.columns.tolist())
print("Sample row:", df.head(1).to_dict(orient="records"))

# Determine column names dynamically
onet_col = next((c for c in df.columns if "onet" in c.lower() or "soc" in c.lower()), df.columns[0])
name_col = next((c for c in df.columns if "occupation" in c.lower() or "title" in c.lower()), None)
exposure_col = next(
    (c for c in df.columns if "overall" in c.lower() and "exposure" in c.lower()),
    next((c for c in df.columns if "exposure" in c.lower()), None),
)

print(f"Using columns: onet={onet_col!r}, name={name_col!r}, exposure={exposure_col!r}")

lookup = {}
for _, row in df.iterrows():
    code = str(row[onet_col]).strip()
    lookup[code] = {
        "occupation_name": str(row[name_col]).strip() if name_col else code,
        "overall_exposure": float(row[exposure_col]) if exposure_col and pd.notna(row[exposure_col]) else 0.5,
    }

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT, "w") as f:
    json.dump(lookup, f, indent=2)

print(f"Saved {len(lookup)} records to {OUTPUT}")
