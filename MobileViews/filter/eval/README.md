# Evaluation Guide

Use this folder to evaluate IDM agent performance on the extracted test subset.

## Files

- `eval.py`: main evaluation entrypoint.
- `agent.py`: model inference agent used by evaluation.
- `generate_eval_preview.py`: HTML preview for evaluation outputs.
- `filter_infeasible_samples.py`: remove marked infeasible samples from `test_subset/split_test.csv`.
- `navigate_back_alt_list.py`: aliases for matching `navigate_back`.
- `outputs/`: generated eval CSV/HTML.

## Default Inputs/Outputs

`eval.py` uses:
- Input metadata: `test_subset/split_test.csv` (fallback: `test_subset/split_test`)
- Input traces: `test_subset/mv_trace_en`
- Output CSV: `eval/outputs/eval_comparison_outputs.csv`

`generate_eval_preview.py` uses:
- Input CSV: `eval/outputs/eval_comparison_outputs.csv`
- Output HTML: `eval/outputs/eval_comparison_preview.html`

## Requirements

```bash
pip install requests pillow
```

Set model environment variables before running:

```bash
export API_KEY="your_key"
export API_URL="https://openrouter.ai/api/v1/chat/completions"
export MODEL="qwen/qwen3-vl-30b-a3b-instruct"
```

## Run Evaluation

Run all test samples:

```bash
python3 eval/eval.py
```

Run only part of test samples:

```bash
python3 eval/eval.py -n 1000
```

Run a random subset with a fixed seed:

```bash
python3 eval/eval.py -n 1000 -s 91010
```

Defaults can also be configured directly in `eval/eval.py`:
- `MAX_TEST_SAMPLES`
- `SAMPLE_SELECTION_SEED`

## Generate Eval Preview

```bash
python3 eval/generate_eval_preview.py
```

For cross-model summary CSV (`any_model_matched` / `all_models_not_matched`):

```bash
python3 eval/build_cross_model_correctness_csv.py
python3 eval/generate_eval_preview.py \
  --csv eval/outputs/cross_model_analysis/all_models_correctness.csv \
  --match-column any_model_matched \
  --output eval/outputs/cross_model_analysis/all_models_correctness_preview.html
```

Open:
- `eval/outputs/eval_comparison_preview.html`

## Mark Infeasible Samples (Human Review)

In `eval_comparison_preview.html`:
- Use `Mark Infeasible` / `Unmark Infeasible` while browsing samples.
- Marks are saved in browser `localStorage`.
- Use `Export Marks JSON` (recommended) or `Export Marks TXT`.

Then move exported file (for example `infeasible_marks.json`) to:
- `eval/outputs/infeasible_marks.json`

## Filter Marked Samples Out of Test Set

```bash
python3 eval/filter_infeasible_samples.py
```

Outputs:
- `test_subset/split_test_feasible.csv`
- `test_subset/split_test_infeasible.csv`
- `eval/outputs/infeasible_filter_summary.txt`

For repeated human-review rounds, run one command:

```bash
bash eval/apply_infeasible_marks.sh
```

This will backup `split_test.csv`, apply filtering, replace `split_test.csv` with feasible rows, and archive removed rows with a timestamp.
