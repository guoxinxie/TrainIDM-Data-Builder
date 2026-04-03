# MobileViews IDM Pipeline

This repo has three core jobs:

1. Filter raw MobileViews transitions into valid/invalid metadata.
2. Build train/test splits and extract a compact test subset.
3. Generate training samples and run evaluation.

## Start Here (By Goal)

### If you want to filter valid/invalid traces
Use:
- `filter_trace.py`
- `generate_filtered_preview.py`
- `generate_filtered_preview.sh`

### If you want to build train/test split metadata
Use:
- `generate_split.py`
- `extract_test_subset.py`

### If you want to generate training samples
See:
- [`train/README.md`](/Users/zli/Documents/mobile-agent/mobileviews/code/TrainIDM-Data-Builder/MobileViews/filter/train/README.md)

### If you want to run evaluation
See:
- [`eval/README.md`](/Users/zli/Documents/mobile-agent/mobileviews/code/TrainIDM-Data-Builder/MobileViews/filter/eval/README.md)

## Minimal Structure

```text
.
├── mv_trace_en/                 # Raw MobileViews traces
├── filtered_metadata/           # Filtered CSV parts + split outputs
├── test_subset/                 # Extracted subset for evaluation
├── train/                       # Training sample generation
├── eval/                        # Evaluation scripts and outputs
├── filter_trace.py
├── generate_filtered_preview.py
├── generate_filtered_preview.sh
├── generate_split.py
└── extract_test_subset.py
```

## Quick Commands

Install dependencies:

```bash
pip install requests pillow
```

Filter raw traces:

```bash
python3 filter_trace.py
```

`filter_trace.py` has two automatic modes:
- If `REFILTER_INPUT_CSV` does not exist (or is empty): run full filtering from `mv_trace_en/` and write to `OUTPUT_CSV`.
- If `REFILTER_INPUT_CSV` exists and is non-empty: re-filter only previous `valid=True` rows in that CSV, then overwrite that CSV (with a timestamped backup file).

Recommended config for second-round re-filtering:
- `REFILTER_INPUT_CSV = "./filtered_metadata/mv_trace_en_all.csv"`
- `ROOT_DIR = "./mv_trace_en"` (or the trace root that matches the CSV)
- `OUTPUT_CSV` is mainly used for first-round full filtering mode.

Combined first-round CSV:
- `filtered_metadata/mv_trace_en_all.csv` (merged from `mv_trace_en1.csv` to `mv_trace_en4.csv`)

Preview filtered results:

```bash
./generate_filtered_preview.sh
```

Build split metadata (reads all `filtered_metadata/*.csv`):

```bash
python3 generate_split.py
```

Extract compact test subset:

```bash
python3 extract_test_subset.py
```
