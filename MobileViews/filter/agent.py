import base64
import json
import os
import time
from typing import Any

import requests

AGENT_CONFIG = {
    "api_key": os.getenv("API_KEY", ""),
    "api_url": os.getenv("API_URL", "https://openrouter.ai/api/v1/chat/completions"),
    "model": os.getenv("MODEL", "qwen/qwen3.5-397b-a17b"),
    "request_timeout": int(os.getenv("REQUEST_TIMEOUT", "120")),
    "max_retries": int(os.getenv("MAX_RETRIES", "3")),
}


ACTION_INFERENCE_PROMPT = """
Given two GUI screens:
- IMAGE 1: before action
- IMAGE 2: after action

Infer one action that causes the transition.
Return exactly one JSON object using one of these action formats:
1. {"action_type": "click", "x": <integer>, "y": <integer>}
2. {"action_type": "input_text", "text": "<text>"}
3. {"action_type": "scroll", "direction": "up" | "left" | "right" | "down"}
4. {"action_type": "navigate_back"}
5. {"action_type": "long_press", "x": <integer>, "y": <integer>}
6. {"action_type": "wait"}

Use absolute coordinates in IMAGE 1 pixel space.
Return JSON only. No extra text.
""".strip()


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

    return {
        "ok": True,
        "action": message_content,
        "raw_output": message_content,
    }


def remote_vlm_agent(before_state_path: str, after_state_path: str):
    return infer_action_from_state_paths(before_state_path, after_state_path)


AGENT_REGISTRY = {
    "remote_vlm": remote_vlm_agent,
}
