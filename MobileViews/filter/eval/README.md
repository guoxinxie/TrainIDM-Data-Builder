# Evaluation Guide

Use this folder to evaluate IDM agent performance on the extracted test subset.

## Files

- `eval.py`: main evaluation entrypoint.
- `agent.py`: model inference agent used by evaluation.
- `generate_eval_preview.py`: HTML preview for evaluation outputs.
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

## Generate Eval Preview

```bash
python3 eval/generate_eval_preview.py
```

Open:
- `eval/outputs/eval_comparison_preview.html`
