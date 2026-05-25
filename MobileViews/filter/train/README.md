# Training Sample Generation

Use this folder to convert split metadata into instruction-tuning JSON samples.

## Which Script To Use

- `generate_rawpixel_train.py`
  - Output action coordinates: raw image pixels.
  - Use for legacy/general pixel-coordinate training targets.

- `generate_qwen3vl_sft_train.py`
  - Output action coordinates: normalized `[0, 1000]`.
  - Use when training Qwen3-VL style data.

- `generate_qwen25vl_sft_train.py`
  - Output action coordinates: Qwen2.5-VL resized-grid coordinates.
  - Use when training Qwen2.5-VL style data.

## Renamed Files

- `mv_for_sft_qwen3vl.py` -> `generate_qwen3vl_sft_train.py`
- `mv_for_sft_qwen25vl.py` -> `generate_qwen25vl_sft_train.py`
- `generate_qwenvl_train.py` -> `generate_rawpixel_train.py`

## Shared Sample Format

```json
{
  "image": ["path/to/before.jpg", "path/to/after.jpg"],
  "conversations": [
    {"from": "human", "value": "<image>\\n<image>\\n..."},
    {"from": "gpt", "value": "{\"action_type\": \"...\"}"}
  ]
}
```

## Important Config (All Scripts)

- `INPUT_SPLIT_CSV`
- `OUTPUT_JSON`
- `TARGET_SPLIT` (usually `train`)
- `IMAGE_PREFIX`

All three scripts now use repo-relative defaults, for example:

```python
TRAIN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TRAIN_DIR.parent
INPUT_SPLIT_CSV = PROJECT_ROOT / "filtered_metadata_3rd" / "split.csv"
IMAGE_PREFIX = PROJECT_ROOT / "mv_trace_en"
```

## Run

```bash
python3 train/generate_rawpixel_train.py
python3 train/generate_qwen3vl_sft_train.py
python3 train/generate_qwen25vl_sft_train.py
```

## Output Defaults

- `train/split_train_qwenvl.json`
- `train/split_train_qwen3vl_sft.json`
- `train/split_train_qwen25vl_sft.json`
