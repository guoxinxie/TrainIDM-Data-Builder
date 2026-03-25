# MobileViews IDM Filter + Visualization

This project filters MobileViews GUI transition pairs for Inverse Dynamics Model (IDM) training/evaluation, and provides an HTML viewer for quick inspection.

Core mapping:

`(Screen 1, Screen 2) -> Action`

## What This Repo Contains

- `filter_trace.py`: main filtering script (VLM-based).
- `generate_transition_preview.py`: generate HTML preview from CSV results.
- `generate_transition_preview.sh`: one-command wrapper to generate preview HTML.

## Requirements

Use Python 3.9+.

Install dependencies:

```bash
pip install requests pillow
```

## Dataset Structure

`filter_trace.py` expects a root directory like this:

```text
mv_trace_en/
  <app_folder_1>/
    utg.js
    states/
      screen_xxx.jpg
  <app_folder_2>/
    utg.js
    states/
      screen_xxx.jpg
```

`utg.js` must contain `nodes`/`edges` with state-image mapping and events.

## Filtering Logic (Current)

The script processes app folders independently (folder-by-folder), and app folders run in parallel via thread pool.

For each app:

- Load all candidate transitions from `utg.js`.
- Skip event types: `intent`, `kill_app`, `wait_user_login`.
- Skip already processed successful rows in existing CSV (resume behavior).
- Sort candidates by trajectory step (`event_id` fallback to scan order).
- Sampling order: midpoint first, then expand to both sides.
- For long trajectories (`LARGE_TRAJECTORY_THRESHOLD`), enforce min step distance (`MIN_STEP_MARGIN`) between selected valid samples.
- Evaluate until app gets up to `MAX_VALID_SAMPLES_PER_APP` new `valid=True` samples.

Before sending to model:

- If action contains `bound_box=...` / `bounding_box=...` / `bbox=...`, Screen 1 is overlaid with a red bbox.
- Screen 2 is unchanged.

Model response handling:

- Logs model `message.content` and token usage (`input/output/total`) to log file.
- Robust JSON parsing with normalization for `TRUE/FALSE/NULL/None` variants.

## Important Configurations

Edit `CONFIG` in `filter_trace.py`:

- `ROOT_DIR`: dataset root.
- `OUTPUT_CSV`: output CSV path.
- `LOG_FILE`: log path.
- `API_URL`: OpenAI-compatible endpoint.
- `MODEL`: model id.
- `MAX_WORKERS`: default parallel folder workers.
- `MAX_VALID_SAMPLES_PER_APP`: per-app valid quota.
<!-- - `LARGE_TRAJECTORY_THRESHOLD`: threshold to enable step-margin rule.
- `MIN_STEP_MARGIN`: minimum sampled step distance for long trajectories.
- `REQUEST_TIMEOUT`, `MAX_RETRIES`. -->

API key is read from environment variable (if using commercial LLM services):

```bash
export API_KEY="your_api_key"
```

[Use vllm to deploy `Qwen3.5-397B-A17B`](https://huggingface.co/Qwen/Qwen3.5-397B-A17B)

```
vllm serve Qwen/Qwen3.5-397B-A17B --port 8000 --tensor-parallel-size 8 --max-model-len 40960 --reasoning-parser qwen3 --host=xx.xx.xx.xx
```

Then fix the `API_URL` and `MODEL` field in `CONFIG`

## How To Run The Filter

Default workers (from config):

```bash
python3 filter_trace.py
```

Override worker count:

```bash
python3 filter_trace.py --max-workers 8
```

## Output Files

### CSV (`filter_mv_trace.csv` by default)

Columns:

- `app_name`
- `from_screen_filename`
- `to_screen_filename`
- `action`
- `valid`
- `action_valid`
- `causal_correct`
- `idm_learnable`
- `violations`
- `reason`

### Log (`filter_mv_trace.log` by default)

Contains:

- scan + sampling stats
- per-app progress
- model response content
- token usage per request
- parse/API errors

## Visualize Results (HTML)

Generate preview HTML:

```bash
./generate_transition_preview.sh
```

Or directly:

```bash
python3 generate_transition_preview.py \
  --csv filter_mv_trace.csv \
  --root-dir mv_trace_en \
  --output filter_mv_trace_preview.html
```

Open `filter_mv_trace_preview.html` in browser.

Viewer features:

- top-level category switch: `Valid` / `Invalid`
- per-category navigation: `Last` / `Next`
- side-by-side Screen 1/Screen 2
- metadata in center panel (app/action/violations/reason)
- Screen 1 bbox highlight parsed from action field

## Notes For Large-Scale Runs

For very large datasets (e.g. 30k+ folders):

- start with moderate `--max-workers` (for example `4~16`) based on API rate limits.
- watch `filter_mv_trace.log` size (it logs model content).
- keep resume CSV on fast disk.

