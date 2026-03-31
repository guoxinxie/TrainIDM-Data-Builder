import csv
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from agent import AGENT_REGISTRY

CSV_PATH = "filter_mv_trace.csv"
TRACE_DIR = "mv_trace_en"
AGENT_NAME = "remote_vlm"
COMPARISON_CSV_PATH = "eval_comparison_outputs.csv"


def _load_navigate_back_alt_list() -> List[str]:
    list_file = Path(__file__).with_name("navigate_back_alt_list.py")
    if not list_file.exists():
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
    "predicted_action",
    "predicted_action_type",
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


def _resolve_state_path(trace_dir: str, app_name: str, filename: str) -> str:
    return os.path.join(trace_dir, app_name, "states", filename)


def extract_valid_true_samples(csv_path: str, trace_dir: str = TRACE_DIR) -> List[Dict[str, Any]]:
    """Read filter_mv_trace.csv and keep rows with valid=TRUE."""
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

    return samples


def run_agents_on_samples(samples: List[Dict[str, Any]], agent_name: str = AGENT_NAME) -> List[Dict[str, Any]]:
    """Feed each sample to one selected agent in agent.py and collect raw outputs."""
    if agent_name not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {agent_name}. Available: {list(AGENT_REGISTRY.keys())}")

    agent_fn = AGENT_REGISTRY[agent_name]
    outputs: List[Dict[str, Any]] = []

    for sample in samples:
        try:
            result = agent_fn(sample["before_state_path"], sample["after_state_path"])
        except Exception as e:
            result = {"ok": False, "error": f"Agent call failed: {e}"}

        predicted_action = str(result.get("action", ""))
        outputs.append(
            {
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
        )

    return outputs


def prepare_comparison_fields(agent_outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prepare comparison/evaluation fields.
    Core evaluation logic is intentionally left blank for now.
    """
    rows: List[Dict[str, Any]] = []

    for item in agent_outputs:
        action_type_match = evaluate_action_type_match(
            item.get("predicted_action", ""),
            item.get("ground_truth_action", ""),
        )
        exact_action_match = evaluate_action(
            item.get("predicted_action", ""),
            item.get("ground_truth_action", ""),
        )
        rows.append(
            {
                "sample_id": item.get("sample_id"),
                "agent_name": item.get("agent_name", ""),
                "app_name": item.get("app_name", ""),
                "before_state_path": item.get("before_state_path", ""),
                "after_state_path": item.get("after_state_path", ""),
                "ground_truth_action": item.get("ground_truth_action", ""),
                "ground_truth_action_type": item.get("ground_truth_action_type", ""),
                "predicted_action": item.get("predicted_action", ""),
                "predicted_action_type": item.get("predicted_action_type", ""),
                "agent_ok": item.get("agent_ok", False),
                "agent_error": item.get("agent_error", ""),
                "agent_raw_output": item.get("agent_raw_output", ""),
                "action_type_match": action_type_match,
                "exact_action_match": exact_action_match,
            }
        )

    return rows


def dump_comparison_fields_to_csv(rows: List[Dict[str, Any]], csv_path: str = COMPARISON_CSV_PATH) -> None:
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARISON_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in COMPARISON_FIELDNAMES})


def load_comparison_fields_from_csv(csv_path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


if __name__ == "__main__":
    if os.path.exists(COMPARISON_CSV_PATH):
        cached_rows = load_comparison_fields_from_csv(COMPARISON_CSV_PATH)
        rows = prepare_comparison_fields(cached_rows)
        dump_comparison_fields_to_csv(rows, COMPARISON_CSV_PATH)

        print(f"Found existing comparison CSV: {COMPARISON_CSV_PATH}")
        print("Skipped model inference. Re-evaluated using cached predictions.")
        print(f"Prepared comparison rows: {len(rows)}")
        print(f"Saved comparison CSV: {COMPARISON_CSV_PATH}")
    else:
        samples = extract_valid_true_samples(CSV_PATH, TRACE_DIR)
        outputs = run_agents_on_samples(samples, AGENT_NAME)
        rows = prepare_comparison_fields(outputs)
        dump_comparison_fields_to_csv(rows, COMPARISON_CSV_PATH)

        print(f"Loaded valid samples: {len(samples)}")
        print(f"Agent outputs: {len(outputs)}")
        print(f"Prepared comparison rows: {len(rows)}")
        print(f"Saved comparison CSV: {COMPARISON_CSV_PATH}")
