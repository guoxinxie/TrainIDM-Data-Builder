import argparse
import csv
import importlib.util
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

try:
    from tqdm import tqdm
except Exception:
    def tqdm(iterable, **kwargs):
        return iterable

EVAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_DIR.parent


def _resolve_test_metadata_csv() -> Path:
    candidates = [
        PROJECT_ROOT / "test_subset" / "split_test.csv",
        PROJECT_ROOT / "test_subset" / "split_test",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


CSV_PATH = _resolve_test_metadata_csv()
TRACE_DIR = PROJECT_ROOT / "test_subset" / "mv_trace_en"
AGENT_NAME = "cot"
AGENT_FILES = {
    "cot": EVAL_DIR / "agent-cot.py",
    "none-cot": EVAL_DIR / "agent-none-cot.py",
    "som": EVAL_DIR / "agent-som.py",
}
OUTPUT_DIR = EVAL_DIR / "outputs"
COMPARISON_CSV_PATH = OUTPUT_DIR / AGENT_NAME / "eval_comparison_outputs.csv"
ERROR_LOG_PATH = OUTPUT_DIR / AGENT_NAME / "eval_agent_errors.log"
# Set to an integer (e.g. 1000) to cap test samples, or None for all samples.
MAX_TEST_SAMPLES = None
# Seed used when randomly selecting MAX_TEST_SAMPLES from all valid test samples.
# Only takes effect when MAX_TEST_SAMPLES is a positive integer.
SAMPLE_SELECTION_SEED = int("91010")
MAX_WORKERS = 12


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate agent on extracted test subset.")
    parser.add_argument(
        "--agent",
        choices=sorted(AGENT_FILES),
        default=AGENT_NAME,
        help=f"Agent to evaluate. Default: {AGENT_NAME}.",
    )
    parser.add_argument(
        "-n",
        "--max-test-samples",
        type=int,
        default=None,
        help="Maximum number of valid test samples to evaluate. Default: use MAX_TEST_SAMPLES in script.",
    )
    parser.add_argument(
        "-w",
        "--max-workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Thread pool size for agent inference. Default: {MAX_WORKERS}.",
    )
    parser.add_argument(
        "-s",
        "--sample-seed",
        type=int,
        default=None,
        help=(
            "Random seed for selecting --max-test-samples from all valid samples. "
            "Default: use SAMPLE_SELECTION_SEED in script."
        ),
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        help=(
            "Comparison output CSV path or filename. "
            "If only a filename is provided, it is saved under eval/outputs/<agent>/."
        ),
    )
    return parser.parse_args()


def _load_navigate_back_alt_list() -> List[str]:
    candidates = [
        EVAL_DIR / "navigate_back_alt_list.py",
    ]
    list_file = None
    for path in candidates:
        if path.exists():
            list_file = path
            break
    if list_file is None:
        return []

    try:
        spec = importlib.util.spec_from_file_location("navigate_back_alt_list_module", str(list_file))
        if spec is None or spec.loader is None:
            return []
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        values = getattr(module, "NAVIGATE_BACK_ALT_LIST", [])
        if not isinstance(values, list):
            return []

        cleaned = []
        seen = set()
        for v in values:
            text = re.sub(r"\s+", " ", str(v or "").strip().lower())
            if text and text not in seen:
                seen.add(text)
                cleaned.append(text)
        return cleaned
    except Exception:
        return []


NAVIGATE_BACK_ALT_LIST = _load_navigate_back_alt_list()
NAVIGATE_BACK_ALT_SET = set(NAVIGATE_BACK_ALT_LIST)

COMPARISON_FIELDNAMES = [
    "sample_id",
    "agent_name",
    "app_name",
    "before_state_path",
    "after_state_path",
    "ground_truth_action",
    "ground_truth_action_type",
    "ground_truth_component_indices",
    "predicted_action",
    "predicted_action_type",
    "predicted_component_index",
    "agent_ok",
    "agent_error",
    "agent_raw_output",
    "action_type_match",
    "exact_action_match",
]


def _extract_action_type(action_text: str) -> str:
    if not action_text:
        return ""

    text = action_text.strip()

    # Predicted format from current agent.py: JSON string.
    try:
        obj = json.loads(text)
        action_type = obj.get("action_type")
        if isinstance(action_type, str):
            return action_type.strip().lower()
    except Exception:
        pass

    # Ground-truth in current CSV is often like: "touch: TouchEvent(...)"
    if ":" in text:
        return text.split(":", 1)[0].strip().lower()

    return ""


def _parse_json_action(action_text: str) -> Dict[str, Any]:
    text = action_text.strip()
    if not text:
        return {}

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}

    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _extract_bbox_from_ground_truth(ground_truth_action: str):
    match = re.search(
        r"(?:bound_box|bounding_box|bbox)\s*=\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
        ground_truth_action,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    x1, y1, x2, y2 = [int(match.group(i)) for i in range(1, 5)]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return left, top, right, bottom


def _is_in_bbox(x: int, y: int, bbox) -> bool:
    left, top, right, bottom = bbox
    return left <= x <= right and top <= y <= bottom


def _state_json_path_from_screenshot(screenshot_path: str) -> Path:
    path = Path(screenshot_path)
    suffix = path.stem[len("screen_"):] if path.stem.startswith("screen_") else path.stem
    return path.with_name(f"state_{suffix}.json")


def _parse_view_bbox(view: Dict[str, Any]):
    raw_bbox = view.get("bound_box")
    if not isinstance(raw_bbox, str):
        return None
    parts = [part.strip() for part in raw_bbox.split(",")]
    if len(parts) != 4 or not all(re.fullmatch(r"-?\d+", part) for part in parts):
        return None
    x1, y1, x2, y2 = map(int, parts)
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def _extract_ground_truth_component_indices(
    ground_truth_action: str, before_state_path: str
) -> List[int]:
    """Map the GT bbox to the exact view indexes shown to the SoM model."""
    ground_truth_bbox = _extract_bbox_from_ground_truth(ground_truth_action)
    if ground_truth_bbox is None:
        return []
    hierarchy_path = _state_json_path_from_screenshot(before_state_path)
    try:
        with open(hierarchy_path, "r", encoding="utf-8") as hierarchy_file:
            views = json.load(hierarchy_file).get("views", [])
    except Exception:
        return []
    return [
        index
        for index, view in enumerate(views)
        if bool(view.get("visible", True))
        and _parse_view_bbox(view) == ground_truth_bbox
    ]


def _extract_predicted_component_index(generated_action: str):
    return _to_int(_parse_json_action(generated_action).get("index"))


def _to_int(value: Any):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("-"):
            if text[1:].isdigit():
                return int(text)
        elif text.isdigit():
            return int(text)
    return None


def _extract_pred_xy(gen_obj: Dict[str, Any]):
    x = gen_obj.get("x")
    y = gen_obj.get("y")

    # Supports format like: {"action_type":"click","x":[497,579]}
    if isinstance(x, (list, tuple)) and len(x) == 2 and (y is None or y == ""):
        x_val = _to_int(x[0])
        y_val = _to_int(x[1])
        if x_val is not None and y_val is not None:
            return x_val, y_val

    x_val = _to_int(x)
    y_val = _to_int(y)
    if x_val is not None and y_val is not None:
        return x_val, y_val
    return None


def _extract_text_from_ground_truth(ground_truth_action: str) -> str:
    match = re.search(r"text\s*=\s*([^,\)\]]+)", ground_truth_action, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip().strip("\"'")


def _extract_scroll_direction_from_ground_truth(ground_truth_action: str) -> str:
    match = re.search(r"direction\s*=\s*([a-zA-Z_]+)", ground_truth_action, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip().lower()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _extract_alt_from_ground_truth(ground_truth_action: str) -> str:
    if not isinstance(ground_truth_action, str):
        return ""

    m = re.search(r"alt\s*=\s*'([^']*)'", ground_truth_action, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'alt\s*=\s*"([^"]*)"', ground_truth_action, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"alt\s*=\s*([^,\]\)]+)", ground_truth_action, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _is_navigate_back_ground_truth(ground_truth_action: str) -> bool:
    alt = _normalize_text(_extract_alt_from_ground_truth(ground_truth_action))
    if not alt:
        return False
    if alt in NAVIGATE_BACK_ALT_SET:
        return True
    if "navigate up" in alt or "nagivate up" in alt or "navigate back" in alt or "go back" in alt:
        return True
    return False


def evaluate_action(generated_action: str, ground_truth_action: str) -> bool:
    """
    Compare model action vs ground-truth action.
    Rules implemented:
    1) input_text: text must be identical.
    2) click vs touch/unselect/select: x,y must be in GT bbox.
    3) scroll: directions must be identical.
    4) long_press vs long_touch: x,y must be in GT bbox.
    5) other actions: TODO placeholder.
    """
    gen_obj = _parse_json_action(generated_action)
    if not gen_obj:
        return False

    gen_type = str(gen_obj.get("action_type", "")).strip().lower()
    gt_type = _extract_action_type(ground_truth_action)

    if gen_type == "input_text":
        gt_text = _extract_text_from_ground_truth(ground_truth_action)
        gen_text = str(gen_obj.get("text", ""))
        return gt_text != "" and gen_text == gt_text

    if gen_type == "click":
        if gt_type not in {"touch", "unselect", "select"}:
            return False
        xy = _extract_pred_xy(gen_obj)
        bbox = _extract_bbox_from_ground_truth(ground_truth_action)
        if xy is None or bbox is None:
            return False
        x, y = xy
        return _is_in_bbox(x, y, bbox)

    if gen_type == "scroll":
        if gt_type != "scroll":
            return False
        gen_dir = str(gen_obj.get("direction", "")).strip().lower()
        gt_dir = _extract_scroll_direction_from_ground_truth(ground_truth_action)
        return gen_dir != "" and gen_dir == gt_dir

    if gen_type == "long_press":
        if gt_type != "long_touch":
            return False
        xy = _extract_pred_xy(gen_obj)
        bbox = _extract_bbox_from_ground_truth(ground_truth_action)
        if xy is None or bbox is None:
            return False
        x, y = xy
        return _is_in_bbox(x, y, bbox)

    if gen_type == "navigate_back":
        return _is_navigate_back_ground_truth(ground_truth_action)

    # TODO: add rules for navigate_back, wait, and other future actions.
    return False


def evaluate_som_action(
    generated_action: str,
    ground_truth_action: str,
    before_state_path: str,
) -> bool:
    """Evaluate SoM target actions by direct component-index equality."""
    gen_obj = _parse_json_action(generated_action)
    if not gen_obj:
        return False
    gen_type = str(gen_obj.get("action_type", "")).strip().lower()
    gt_type = _extract_action_type(ground_truth_action)

    if gen_type == "navigate_back":
        return _is_navigate_back_ground_truth(ground_truth_action)
    if gen_type == "wait":
        return False

    type_matches = {
        "click": gt_type in {"touch", "unselect", "select"},
        "input_text": gt_type in {"set_text", "input_text"},
        "scroll": gt_type == "scroll",
        "long_press": gt_type == "long_touch",
    }
    if not type_matches.get(gen_type, False):
        return False

    predicted_index = _to_int(gen_obj.get("index"))
    ground_truth_indices = _extract_ground_truth_component_indices(
        ground_truth_action, before_state_path
    )
    if predicted_index is None or predicted_index not in ground_truth_indices:
        return False

    if gen_type == "input_text":
        return str(gen_obj.get("text", "")) == _extract_text_from_ground_truth(
            ground_truth_action
        )
    if gen_type == "scroll":
        return str(gen_obj.get("direction", "")).strip().lower() == (
            _extract_scroll_direction_from_ground_truth(ground_truth_action)
        )
    return True


def evaluate_action_type_match(generated_action: str, ground_truth_action: str) -> bool:
    gen_type = str(_parse_json_action(generated_action).get("action_type", "")).strip().lower()
    gt_type = _extract_action_type(ground_truth_action)

    if gen_type == "input_text":
        return gt_type in {"set_text", "input_text"}
    if gen_type == "click":
        return gt_type in {"touch", "unselect", "select"}
    if gen_type == "scroll":
        return gt_type == "scroll"
    if gen_type == "long_press":
        return gt_type == "long_touch"
    if gen_type == "navigate_back":
        return _is_navigate_back_ground_truth(ground_truth_action)

    # TODO: add rules for navigate_back, wait, and other future actions.
    return False


def _resolve_state_path(trace_dir, app_name: str, filename: str) -> str:
    return str(Path(trace_dir) / app_name / "states" / filename)


def extract_valid_true_samples(
    csv_path,
    trace_dir=TRACE_DIR,
    max_samples=MAX_TEST_SAMPLES,
    sample_seed=SAMPLE_SELECTION_SEED,
) -> List[Dict[str, Any]]:
    """Read split_test CSV, keep rows with valid=TRUE, and optionally random-sample by seed."""
    samples: List[Dict[str, Any]] = []

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            if str(row.get("valid", "")).strip().lower() != "true":
                continue

            app_name = row.get("app_name", "").strip()
            from_file = row.get("from_screen_filename", "").strip()
            to_file = row.get("to_screen_filename", "").strip()
            gt_action = row.get("action", "").strip()

            samples.append(
                {
                    "sample_id": idx,
                    "app_name": app_name,
                    "before_state_path": _resolve_state_path(trace_dir, app_name, from_file),
                    "after_state_path": _resolve_state_path(trace_dir, app_name, to_file),
                    "ground_truth_action": gt_action,
                    "ground_truth_action_type": _extract_action_type(gt_action),
                }
            )

    if isinstance(max_samples, int) and max_samples > 0 and len(samples) > max_samples:
        rng = random.Random(sample_seed)
        samples = rng.sample(samples, max_samples)

    return samples


def _load_agent_registry(agent_name: str):
    agent_path = AGENT_FILES[agent_name]
    spec = importlib.util.spec_from_file_location(
        f"eval_agent_{agent_name.replace('-', '_')}", str(agent_path)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load agent from {agent_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registry = getattr(module, "AGENT_REGISTRY", {})
    if agent_name in registry:
        return {agent_name: registry[agent_name]}
    if len(registry) == 1:
        return {agent_name: next(iter(registry.values()))}
    raise ValueError(f"No callable registered for agent '{agent_name}' in {agent_path}")


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def log_agent_errors(records: List[Dict[str, Any]], log_path=ERROR_LOG_PATH) -> int:
    messages = []
    for item in records:
        agent_ok = _parse_bool(item.get("agent_ok"))
        agent_error = str(item.get("agent_error", "")).strip()
        if agent_ok is False or agent_error:
            sample_id = item.get("sample_id", "")
            app_name = item.get("app_name", "")
            error_text = agent_error if agent_error else "agent_ok=false (empty agent_error)"
            msg = f"[agent_error] sample_id={sample_id} app_name={app_name} error={error_text}"
            messages.append(msg)

    log_path = Path(log_path)
    if log_path.exists():
        log_path.unlink()

    if not messages:
        print("Agent errors: 0")
        return 0

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(messages) + "\n")

    print(f"Agent errors: {len(messages)}")
    print(f"Error log saved: {log_path}")
    for msg in messages:
        print(msg)

    return len(messages)


def run_agents_on_samples(
    samples: List[Dict[str, Any]],
    agent_name: str = AGENT_NAME,
    max_workers: int = MAX_WORKERS,
) -> List[Dict[str, Any]]:
    """Feed each sample to one selected agent in agent.py and collect raw outputs."""
    AGENT_REGISTRY = _load_agent_registry(agent_name)
    if agent_name not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {agent_name}. Available: {list(AGENT_REGISTRY.keys())}")

    agent_fn = AGENT_REGISTRY[agent_name]
    outputs: List[Dict[str, Any]] = [None] * len(samples)

    def _run_one(sample: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = agent_fn(sample["before_state_path"], sample["after_state_path"])
        except Exception as e:
            result = {"ok": False, "error": f"Agent call failed: {e}"}

        predicted_action = str(result.get("action", ""))
        return {
            "sample_id": sample["sample_id"],
            "agent_name": agent_name,
            "app_name": sample["app_name"],
            "before_state_path": sample["before_state_path"],
            "after_state_path": sample["after_state_path"],
            "ground_truth_action": sample["ground_truth_action"],
            "ground_truth_action_type": sample["ground_truth_action_type"],
            "agent_ok": bool(result.get("ok", False)),
            "agent_error": str(result.get("error", "")),
            "predicted_action": predicted_action,
            "predicted_action_type": _extract_action_type(predicted_action),
            "agent_raw_output": str(result.get("raw_output", "")),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(_run_one, sample): idx
            for idx, sample in enumerate(samples)
        }
        for future in tqdm(
            as_completed(future_to_index),
            total=len(samples),
            desc="Evaluating",
            unit="sample",
        ):
            idx = future_to_index[future]
            outputs[idx] = future.result()

    return outputs


def prepare_comparison_row(item: Dict[str, Any]) -> Dict[str, Any]:
    action_type_match = evaluate_action_type_match(
        item.get("predicted_action", ""),
        item.get("ground_truth_action", ""),
    )
    if item.get("agent_name") == "som":
        exact_action_match = evaluate_som_action(
            item.get("predicted_action", ""),
            item.get("ground_truth_action", ""),
            item.get("before_state_path", ""),
        )
        ground_truth_component_indices = _extract_ground_truth_component_indices(
            item.get("ground_truth_action", ""), item.get("before_state_path", "")
        )
        predicted_component_index = _extract_predicted_component_index(
            item.get("predicted_action", "")
        )
    else:
        exact_action_match = evaluate_action(
            item.get("predicted_action", ""),
            item.get("ground_truth_action", ""),
        )
        ground_truth_component_indices = []
        predicted_component_index = None
    return {
        "sample_id": item.get("sample_id"),
        "agent_name": item.get("agent_name", ""),
        "app_name": item.get("app_name", ""),
        "before_state_path": item.get("before_state_path", ""),
        "after_state_path": item.get("after_state_path", ""),
        "ground_truth_action": item.get("ground_truth_action", ""),
        "ground_truth_action_type": item.get("ground_truth_action_type", ""),
        "ground_truth_component_indices": json.dumps(ground_truth_component_indices),
        "predicted_action": item.get("predicted_action", ""),
        "predicted_action_type": item.get("predicted_action_type", ""),
        "predicted_component_index": predicted_component_index,
        "agent_ok": item.get("agent_ok", False),
        "agent_error": item.get("agent_error", ""),
        "agent_raw_output": item.get("agent_raw_output", ""),
        "action_type_match": action_type_match,
        "exact_action_match": exact_action_match,
    }


def run_agents_on_samples_stream_to_csv(
    samples: List[Dict[str, Any]],
    csv_path=COMPARISON_CSV_PATH,
    agent_name: str = AGENT_NAME,
    max_workers: int = MAX_WORKERS,
) -> List[Dict[str, Any]]:
    """
    Run inference and stream comparison rows to CSV during evaluation.
    Rows are flushed in input order as soon as each contiguous prefix is ready.
    """
    AGENT_REGISTRY = _load_agent_registry(agent_name)
    if agent_name not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {agent_name}. Available: {list(AGENT_REGISTRY.keys())}")

    agent_fn = AGENT_REGISTRY[agent_name]
    outputs: List[Dict[str, Any]] = [None] * len(samples)

    def _run_one(sample: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = agent_fn(sample["before_state_path"], sample["after_state_path"])
        except Exception as e:
            result = {"ok": False, "error": f"Agent call failed: {e}"}

        predicted_action = str(result.get("action", ""))
        return {
            "sample_id": sample["sample_id"],
            "agent_name": agent_name,
            "app_name": sample["app_name"],
            "before_state_path": sample["before_state_path"],
            "after_state_path": sample["after_state_path"],
            "ground_truth_action": sample["ground_truth_action"],
            "ground_truth_action_type": sample["ground_truth_action_type"],
            "agent_ok": bool(result.get("ok", False)),
            "agent_error": str(result.get("error", "")),
            "predicted_action": predicted_action,
            "predicted_action_type": _extract_action_type(predicted_action),
            "agent_raw_output": str(result.get("raw_output", "")),
        }

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARISON_FIELDNAMES)
        writer.writeheader()
        f.flush()

        pending_rows: Dict[int, Dict[str, Any]] = {}
        next_write_idx = 0
        total_samples = len(samples)
        completed_samples = 0
        correct_samples = 0
        progress_log_interval = 50

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(_run_one, sample): idx
                for idx, sample in enumerate(samples)
            }
            for future in tqdm(
                as_completed(future_to_index),
                total=len(samples),
                desc="Evaluating",
                unit="sample",
            ):
                idx = future_to_index[future]
                output = future.result()
                outputs[idx] = output
                comparison_row = prepare_comparison_row(output)
                pending_rows[idx] = comparison_row

                completed_samples += 1
                if bool(comparison_row.get("exact_action_match")):
                    correct_samples += 1

                if (
                    completed_samples % progress_log_interval == 0
                    or completed_samples == total_samples
                ):
                    print(
                        f"[progress] correct={correct_samples}/{completed_samples} "
                        f"(completed={completed_samples}/{total_samples})"
                    )

                wrote_any = False
                while next_write_idx in pending_rows:
                    row = pending_rows.pop(next_write_idx)
                    writer.writerow({key: row.get(key) for key in COMPARISON_FIELDNAMES})
                    next_write_idx += 1
                    wrote_any = True
                if wrote_any:
                    f.flush()

    return outputs


def prepare_comparison_fields(agent_outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prepare comparison/evaluation fields.
    Core evaluation logic is intentionally left blank for now.
    """
    rows: List[Dict[str, Any]] = []

    for item in agent_outputs:
        rows.append(prepare_comparison_row(item))

    return rows


def dump_comparison_fields_to_csv(rows: List[Dict[str, Any]], csv_path=COMPARISON_CSV_PATH) -> None:
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARISON_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in COMPARISON_FIELDNAMES})


def load_comparison_fields_from_csv(csv_path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


if __name__ == "__main__":
    args = parse_args()
    if args.max_test_samples is not None and args.max_test_samples <= 0:
        raise ValueError("--max-test-samples must be a positive integer.")
    if args.max_workers is not None and args.max_workers <= 0:
        raise ValueError("--max-workers must be a positive integer.")

    effective_max_test_samples = (
        args.max_test_samples if args.max_test_samples is not None else MAX_TEST_SAMPLES
    )
    effective_sample_seed = (
        args.sample_seed if args.sample_seed is not None else SAMPLE_SELECTION_SEED
    )
    effective_max_workers = args.max_workers if args.max_workers is not None else MAX_WORKERS
    effective_agent_name = args.agent
    agent_output_dir = OUTPUT_DIR / effective_agent_name
    if args.output_csv:
        requested_output = Path(args.output_csv)
        if requested_output.parent == Path("."):
            effective_comparison_csv = agent_output_dir / requested_output.name
        else:
            effective_comparison_csv = requested_output
    else:
        effective_comparison_csv = agent_output_dir / "eval_comparison_outputs.csv"
    effective_error_log = agent_output_dir / "eval_agent_errors.log"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    is_sampling_mode = isinstance(effective_max_test_samples, int) and effective_max_test_samples > 0

    # In sampling mode, always run fresh inference because subset selection can change.
    if effective_comparison_csv.exists() and not is_sampling_mode:
        cached_rows = load_comparison_fields_from_csv(effective_comparison_csv)
        cached_agents = {row.get("agent_name", "") for row in cached_rows}
        if cached_agents and cached_agents != {effective_agent_name}:
            raise ValueError(
                f"Cached CSV was produced by {sorted(cached_agents)}, not "
                f"'{effective_agent_name}'. Choose another --output-csv."
            )
        rows = prepare_comparison_fields(cached_rows)
        dump_comparison_fields_to_csv(rows, effective_comparison_csv)

        print(f"Found existing comparison CSV: {effective_comparison_csv}")
        print("Skipped model inference. Re-evaluated using cached predictions.")
        print(f"Agent: {effective_agent_name}")
        print(f"Max test samples: {effective_max_test_samples}")
        print(f"Sample seed: {effective_sample_seed} (ignored when max test samples is None)")
        print(f"Max workers: {effective_max_workers}")
        print(f"Prepared comparison rows: {len(rows)}")
        print(f"Saved comparison CSV: {effective_comparison_csv}")
        log_agent_errors(cached_rows, effective_error_log)
    else:
        samples = extract_valid_true_samples(
            CSV_PATH,
            TRACE_DIR,
            effective_max_test_samples,
            effective_sample_seed,
        )
        outputs = run_agents_on_samples_stream_to_csv(
            samples=samples,
            csv_path=effective_comparison_csv,
            agent_name=effective_agent_name,
            max_workers=effective_max_workers,
        )

        print(f"Agent: {effective_agent_name}")
        print(f"Loaded valid samples: {len(samples)}")
        print(f"Max test samples: {effective_max_test_samples}")
        print(f"Sample seed: {effective_sample_seed}")
        print(f"Max workers: {effective_max_workers}")
        print(f"Agent outputs: {len(outputs)}")
        print(f"Prepared comparison rows: {len(outputs)}")
        print(f"Saved comparison CSV: {effective_comparison_csv}")
        log_agent_errors(outputs, effective_error_log)
