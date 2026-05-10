# Training Sample Generation

Use this folder to convert split metadata into Qwen-style training JSON.

## File

- `generate_qwenvl_train.py`: converts MobileViews actions to Qwen-style action JSON and builds conversation samples.

## What It Produces

Each sample has this format:

```json
{
  "image": ["path/to/before.jpg", "path/to/after.jpg"],
  "conversations": [
    {"from": "human", "value": "<image>\n<image>\n..."},
    {"from": "gpt", "value": "{\"action_type\": \"...\"}"}
  ]
}
```

## Important Config

In `train/generate_qwenvl_train.py`, check:
- `INPUT_SPLIT_CSV`
- `OUTPUT_JSON`
- `TARGET_SPLIT` (usually `train`)
- `IMAGE_PREFIX`

Current defaults are:

```python
INPUT_SPLIT_CSV = PROJECT_ROOT / "filtered_metadata_3rd" / "split.csv"
OUTPUT_JSON = TRAIN_DIR / "split_train_qwenvl.json"
TARGET_SPLIT = "train"
IMAGE_PREFIX = PROJECT_ROOT / "mv_trace_en"
```

To build test JSON, change:

```python
TARGET_SPLIT = "test"
OUTPUT_JSON = TRAIN_DIR / "split_test_qwenvl.json"
```

## Run

```bash
python3 train/generate_qwenvl_train.py
```

## Output

- JSON file defined by `OUTPUT_JSON` (default: `train/split_train_qwenvl.json`).
