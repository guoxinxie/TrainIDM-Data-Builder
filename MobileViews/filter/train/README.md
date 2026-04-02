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

If your split file is in `filtered_metadata/split.csv`, set:

```python
INPUT_SPLIT_CSV = "filtered_metadata/split.csv"
```

## Run

```bash
python3 train/generate_qwenvl_train.py
```

## Output

- JSON file defined by `OUTPUT_JSON` (default currently `split_train_qwenvl.json`).
