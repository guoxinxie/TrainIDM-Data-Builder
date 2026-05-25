import base64
import json
import os
import re
import time
import math
from typing import Any, Optional, Tuple

import requests
from PIL import Image

AGENT_CONFIG = {
    "api_key": os.getenv("API_KEY", ""),
    "api_url": os.getenv("API_URL", "https://openrouter.ai/api/v1/chat/completions"),
    # "api_url": os.getenv("API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
    # "model": os.getenv("MODEL", "qwen/qwen3.5-397b-a17b"),
    # "model": os.getenv("MODEL", "qwen/qwen3-vl-235b-a22b-instruct"),
    # "model": os.getenv("MODEL", "qwen/qwen3-vl-32b-instruct"),
    "model": os.getenv("MODEL", "bytedance/ui-tars-1.5-7b"),
    # "model": os.getenv("MODEL", "google/gemini-3.1-pro-preview"),
    "request_timeout": int(os.getenv("REQUEST_TIMEOUT", "120")),
    "max_retries": int(os.getenv("MAX_RETRIES", "3")),
}


ACTION_INFERENCE_PROMPT = """
You are an expert mobile UI automation agent. You are given two screenshots of a mobile application:
- IMAGE 1: The UI state BEFORE an action is taken.
- IMAGE 2: The UI state AFTER an action is taken.

Your task is to deduce the single user action performed on IMAGE 1 that caused the transition to IMAGE 2.

### INSTRUCTIONS:
1. Compare IMAGE 1 and IMAGE 2. Identify what changed (e.g., a new menu opened, the screen scrolled, a button changed color, text was entered).
2. Locate the exact UI element in IMAGE 1 that was interacted with to cause this change.
3. Determine the absolute pixel coordinates (x, y) of the CENTER of that UI element in IMAGE 1. The coordinate (0,0) is the top-left corner of the image.
4. If the screen scrolled, determine the direction. Note: "scroll down" means the page content moved up so that lower content became visible.

### ACTION SCHEMA:
Choose exactly ONE action from the following formats:
1. {"action_type": "click", "x": <integer>, "y": <integer>}
2. {"action_type": "input_text", "text": "<text>"}
3. {"action_type": "scroll", "direction": "up" | "left" | "right" | "down"}
4. {"action_type": "navigate_back"}
5. {"action_type": "long_press", "x": <integer>, "y": <integer>}
6. {"action_type": "wait"}

### OUTPUT:
First, provide a brief, step-by-step reasoning of the visual changes and how you deduced the action.
Then, output the precise action in a standard JSON code block.
""".strip()

# copy from: qwen2.5vl vision_process.py
MAX_RATIO = 200
SPATIAL_MERGE_SIZE = 2
IMAGE_MIN_TOKEN_NUM = 4
IMAGE_MAX_TOKEN_NUM = 16384
FACTOR = 28


def round_by_factor(number: int, factor: int) -> int:
    """Returns the closest integer to 'number' that is divisible by 'factor'."""
    return round(number / factor) * factor


def ceil_by_factor(number: int, factor: int) -> int:
    """Returns the smallest integer greater than or equal to 'number' that is divisible by 'factor'."""
    return math.ceil(number / factor) * factor


def floor_by_factor(number: int, factor: int) -> int:
    """Returns the largest integer less than or equal to 'number' that is divisible by 'factor'."""
    return math.floor(number / factor) * factor


def smart_resize(height: int, width: int, factor: int = FACTOR, min_pixels: Optional[int] = None, max_pixels: Optional[int] = None) -> Tuple[int, int]:
    """
    Rescales the image so that the following conditions are met:

    1. Both dimensions (height and width) are divisible by 'factor'.
    2. The total number of pixels is within the range ['min_pixels', 'max_pixels'].
    3. The aspect ratio of the image is maintained as closely as possible.
    """
    max_pixels = max_pixels if max_pixels is not None else (IMAGE_MAX_TOKEN_NUM * factor ** 2)
    min_pixels = min_pixels if min_pixels is not None else (IMAGE_MIN_TOKEN_NUM * factor ** 2)
    assert max_pixels >= min_pixels, "The max_pixels of image must be greater than or equal to min_pixels."
    if max(height, width) / min(height, width) > MAX_RATIO:
        raise ValueError(
            f"absolute aspect ratio must be smaller than {MAX_RATIO}, got {max(height, width) / min(height, width)}"
        )
    h_bar = max(factor, round_by_factor(height, factor))
    w_bar = max(factor, round_by_factor(width, factor))
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = floor_by_factor(height / beta, factor)
        w_bar = floor_by_factor(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = ceil_by_factor(height * beta, factor)
        w_bar = ceil_by_factor(width * beta, factor)
    return h_bar, w_bar


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return "\n".join(x for x in text_parts if x)
    return "" if content is None else str(content)


def _parse_action_json(action_text: str):
    text = (action_text or "").strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    # Fallback: extract the first JSON object from model output.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _is_qwen3_vl_model(model_name: str) -> bool:
    name = (model_name or "").lower()
    return "qwen3-vl" in name


def _is_qwen25_vl_model(model_name: str) -> bool:
    name = (model_name or "").lower()
    return "qwen2.5-vl" in name or "qwen25-vl" in name or "mimo" in name or "ui-tars" in name


def _convert_qwen3_vl_xy_to_pixels(action_obj: dict, before_state_path: str):
    action_type = action_obj.get("action_type")
    if action_type not in {"click", "long_press"}:
        return action_obj
    if "x" not in action_obj or "y" not in action_obj:
        return action_obj

    try:
        x_norm = float(action_obj["x"])
        y_norm = float(action_obj["y"])
    except Exception:
        return action_obj

    with Image.open(before_state_path) as img:
        width, height = img.size

    # Qwen3-VL grounding coordinates are normalized in [0, 1000].
    x_pixel = int(round((x_norm / 1000.0) * width))
    y_pixel = int(round((y_norm / 1000.0) * height))
    x_pixel = max(0, min(x_pixel, max(width - 1, 0)))
    y_pixel = max(0, min(y_pixel, max(height - 1, 0)))

    action_obj["x"] = x_pixel
    action_obj["y"] = y_pixel
    return action_obj


def _convert_qwen25_vl_xy_to_pixels(action_obj: dict, before_state_path: str):
    action_type = action_obj.get("action_type")
    if action_type not in {"click", "long_press"}:
        return action_obj
    if "x" not in action_obj or "y" not in action_obj:
        return action_obj

    try:
        x_norm = float(action_obj["x"])
        y_norm = float(action_obj["y"])
    except Exception:
        return action_obj

    with Image.open(before_state_path) as img:
        width, height = img.size

    resized_h, resized_w = smart_resize(height, width)
    # Qwen2.5-VL grounding coordinates are normalized in resized image.
    x_pixel = int(round((x_norm / resized_w) * width))
    y_pixel = int(round((y_norm / resized_h) * height))
    x_pixel = max(0, min(x_pixel, max(width - 1, 0)))
    y_pixel = max(0, min(y_pixel, max(height - 1, 0)))

    action_obj["x"] = x_pixel
    action_obj["y"] = y_pixel
    return action_obj


def _postprocess_action_by_model(action_text: str, before_state_path: str):
    action_obj = _parse_action_json(action_text)
    if not isinstance(action_obj, dict):
        return action_text

    model_name = AGENT_CONFIG.get("model", "")

    if _is_qwen3_vl_model(model_name):
        action_obj = _convert_qwen3_vl_xy_to_pixels(action_obj, before_state_path)
    elif _is_qwen25_vl_model(model_name):
        action_obj = _convert_qwen25_vl_xy_to_pixels(action_obj, before_state_path)

    return json.dumps(action_obj, ensure_ascii=False)


def _call_remote_model(messages: list):
    headers = {"Content-Type": "application/json"}
    if AGENT_CONFIG.get("api_key"):
        headers["Authorization"] = f"Bearer {AGENT_CONFIG['api_key']}"

    payload = {
        "model": AGENT_CONFIG["model"],
        "messages": messages,
        "temperature": 0,
    }

    last_error = None
    for attempt in range(AGENT_CONFIG["max_retries"]):
        try:
            response = requests.post(
                AGENT_CONFIG["api_url"],
                headers=headers,
                data=json.dumps(payload),
                timeout=AGENT_CONFIG["request_timeout"],
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices or "message" not in choices[0]:
                return {"ok": False, "error": "Unexpected API response schema", "raw_response": response.text}

            text = _content_to_text(choices[0]["message"].get("content"))
            return {"ok": True, "message_content": text, "raw_response": response.text}
        except Exception as e:
            last_error = str(e)
            time.sleep(2 ** attempt)

    return {"ok": False, "error": f"Remote request failed: {last_error}"}


def infer_action_from_state_paths(before_state_path: str, after_state_path: str):
    """
    Infer the transition action from before/after GUI screenshots via a remote VLM.
    Return schema:
    - success: {"ok": True, "action": str, "raw_output": str}
    - failure: {"ok": False, "error": str, "raw_response"?: str}
    """
    before_b64 = _encode_image(before_state_path)
    after_b64 = _encode_image(after_state_path)

    content = [
        {"type": "text", "text": ACTION_INFERENCE_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{before_b64}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{after_b64}"}},
    ]
    messages = [{"role": "user", "content": content}]

    model_result = _call_remote_model(messages)
    if not model_result.get("ok"):
        return model_result

    message_content = model_result.get("message_content", "")
    postprocessed_action = _postprocess_action_by_model(message_content, before_state_path)

    return {
        "ok": True,
        "action": postprocessed_action,
        "raw_output": message_content,
    }


def remote_vlm_agent(before_state_path: str, after_state_path: str):
    return infer_action_from_state_paths(before_state_path, after_state_path)


AGENT_REGISTRY = {
    "remote_vlm": remote_vlm_agent,
}
