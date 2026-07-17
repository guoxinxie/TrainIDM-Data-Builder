"""Screenshot-pair IDM agent that returns action JSON without explicit CoT."""

import importlib.util
import json
from pathlib import Path


def _load_cot_agent_module():
    path = Path(__file__).resolve().with_name("agent-cot.py")
    spec = importlib.util.spec_from_file_location("agent_cot_shared", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load shared agent helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_cot_agent_module()
AGENT_CONFIG = _BASE.AGENT_CONFIG


ACTION_INFERENCE_PROMPT = """
You are an expert mobile UI automation agent. You are given two screenshots of a mobile application:
- IMAGE 1: The UI state BEFORE an action is taken.
- IMAGE 2: The UI state AFTER an action is taken.

Your task is to deduce the single user action performed on IMAGE 1 that caused the transition to IMAGE 2.

### INSTRUCTIONS:
1. Compare IMAGE 1 and IMAGE 2 and identify what changed.
2. Locate the exact UI element in IMAGE 1 that was interacted with.
3. Determine the absolute pixel coordinates (x, y) of the CENTER of that UI element in IMAGE 1. The coordinate (0,0) is the top-left corner.
4. If the screen scrolled, determine the direction. "scroll down" means the page content moved up so that lower content became visible.

### ACTION SCHEMA:
Choose exactly ONE action from the following formats:
1. {"action_type": "click", "x": <integer>, "y": <integer>}
2. {"action_type": "input_text", "text": "<text>"}
3. {"action_type": "scroll", "direction": "up" | "left" | "right" | "down"}
4. {"action_type": "navigate_back"}
5. {"action_type": "long_press", "x": <integer>, "y": <integer>}
6. {"action_type": "wait"}

### OUTPUT:
Return exactly one valid JSON object containing the action. Do not include reasoning, prose, or Markdown fences.
""".strip()


def infer_action_from_state_paths(before_state_path: str, after_state_path: str):
    before_b64 = _BASE._encode_image(before_state_path)
    after_b64 = _BASE._encode_image(after_state_path)
    content = [
        {"type": "text", "text": ACTION_INFERENCE_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{before_b64}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{after_b64}"}},
    ]
    model_result = _BASE._call_remote_model([{"role": "user", "content": content}])
    if not model_result.get("ok"):
        return model_result

    message_content = model_result.get("message_content", "")
    action_obj = _BASE._parse_action_json(message_content)
    if not isinstance(action_obj, dict):
        return {
            "ok": False,
            "error": "Model output does not contain valid action JSON",
            "raw_output": message_content,
        }

    postprocessed_action = _BASE._postprocess_action_by_model(
        json.dumps(action_obj, ensure_ascii=False), before_state_path
    )
    return {
        "ok": True,
        "action": postprocessed_action,
        "raw_output": message_content,
    }


def remote_vlm_agent(before_state_path: str, after_state_path: str):
    return infer_action_from_state_paths(before_state_path, after_state_path)


AGENT_REGISTRY = {"none-cot": remote_vlm_agent}
