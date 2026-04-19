#!/usr/bin/env python3
import argparse
import csv
import importlib.util
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = EVAL_DIR / "outputs" / "eval_comparison_outputs.csv"


def configure_csv_field_size_limit():
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit = limit // 10


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_bool(value: Any):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def is_agent_error_row(row: Dict[str, Any]) -> bool:
    agent_ok = parse_bool(row.get("agent_ok"))
    agent_error = str(row.get("agent_error", "")).strip()
    return agent_ok is False or agent_error != ""


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Rerun only rows with agent errors in eval_comparison_outputs.csv and update results."
        )
    )
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Input eval CSV path.")
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Output CSV path. Default: overwrite --csv in place.",
    )
    parser.add_argument(
        "--agent-name",
        default="remote_vlm",
        help="Agent key in eval/agent.py AGENT_REGISTRY (default: remote_vlm).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Thread pool size for rerun inference (default: 8).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count agent-error rows, do not rerun.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="When overwriting input CSV, skip creating timestamped backup.",
    )
    return parser.parse_args()


def main():
    configure_csv_field_size_limit()
    args = parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    output_csv = Path(args.output_csv).resolve() if args.output_csv else csv_path

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    required_fields = {
        "sample_id",
        "before_state_path",
        "after_state_path",
        "ground_truth_action",
        "predicted_action",
        "predicted_action_type",
        "agent_ok",
        "agent_error",
        "agent_raw_output",
        "action_type_match",
        "exact_action_match",
    }
    missing = sorted(required_fields - set(fieldnames))
    if missing:
        raise ValueError(f"Input CSV missing required columns: {missing}")

    error_indices = [i for i, row in enumerate(rows) if is_agent_error_row(row)]
    print(f"Total rows: {len(rows)}")
    print(f"Agent-error rows to rerun: {len(error_indices)}")

    if args.dry_run or not error_indices:
        return

    if args.max_workers <= 0:
        raise ValueError("--max-workers must be a positive integer.")

    eval_module = load_module(EVAL_DIR / "eval.py", "eval_module_for_rerun")
    agent_module = load_module(EVAL_DIR / "agent.py", "agent_module_for_rerun")
    agent_registry = getattr(agent_module, "AGENT_REGISTRY", {})
    if args.agent_name not in agent_registry:
        raise ValueError(
            f"Unknown agent '{args.agent_name}'. Available: {sorted(agent_registry.keys())}"
        )
    agent_fn = agent_registry[args.agent_name]

    def rerun_one(index_and_row: Tuple[int, Dict[str, Any]]):
        idx, row = index_and_row
        before_state = str(row.get("before_state_path", "")).strip()
        after_state = str(row.get("after_state_path", "")).strip()
        gt_action = str(row.get("ground_truth_action", "")).strip()

        try:
            result = agent_fn(before_state, after_state)
        except Exception as e:
            result = {"ok": False, "error": f"Agent call failed: {e}"}

        predicted_action = str(result.get("action", ""))
        updated = dict(row)
        updated["agent_ok"] = bool(result.get("ok", False))
        updated["agent_error"] = str(result.get("error", ""))
        updated["predicted_action"] = predicted_action
        updated["predicted_action_type"] = eval_module._extract_action_type(predicted_action)
        updated["agent_raw_output"] = str(result.get("raw_output", ""))
        updated["action_type_match"] = eval_module.evaluate_action_type_match(predicted_action, gt_action)
        updated["exact_action_match"] = eval_module.evaluate_action(predicted_action, gt_action)
        return idx, updated

    updated_count = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [
            executor.submit(rerun_one, (idx, rows[idx]))
            for idx in error_indices
        ]
        for future in as_completed(futures):
            idx, updated_row = future.result()
            rows[idx] = updated_row
            updated_count += 1
            if updated_count % 50 == 0 or updated_count == len(error_indices):
                print(f"[progress] rerun_done={updated_count}/{len(error_indices)}")

    if output_csv == csv_path and not args.no_backup:
        backup_path = csv_path.with_name(
            f"{csv_path.name}.backup_before_rerun_errors_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(csv_path, backup_path)
        print(f"Backup created: {backup_path}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    remaining_errors = sum(1 for row in rows if is_agent_error_row(row))
    print(f"Saved: {output_csv}")
    print(f"Rows rerun: {updated_count}")
    print(f"Remaining agent-error rows: {remaining_errors}")


if __name__ == "__main__":
    main()
