import argparse
import base64
import csv
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

# --- 配置区 ---
CONFIG = {
    # ================= 路径配置区 =================
    "ROOT_DIR": "./mv_trace_en",  # 输入端：原始数据集的根目录。程序会遍历该目录下的各个 APP 文件夹读取 utg.js 和截图
    "REFILTER_INPUT_CSV": "./filtered_metadata/mv_trace_en_all.csv",  # 二轮过滤输入：若该文件存在且非空，则仅对其中 valid=True 的样本复检
    "OUTPUT_CSV": "./filter_mv_trace.csv",  # 输出端：模型评估结果的保存路径。支持断点续传，已存在的数据会自动跳过
    "LOG_FILE": "./filter_mv_trace.log",  # 日志端：运行日志保存路径，用于排查报错（如 API 异常、图片读取失败等）

    # ================= 大模型 API 配置区 =================
    # 支持任何兼容 OpenAI 接口格式的服务（如 OpenRouter、本地部署的 vLLM、Ollama 等）
    "API_KEY": os.getenv("API_KEY", ""),  # 从环境变量 API_KEY 读取；本地无鉴权服务可留空
    "API_URL": "https://openrouter.ai/api/v1/chat/completions",
    # API 请求地址。若使用本地 vLLM，通常改为 "http://localhost:8000/v1/chat/completions"
    "MODEL": "qwen/qwen3.5-397b-a17b",  # 调用的具体视觉模型名称。必须与提供商（或本地部署）的模型列表名称严格一致

    # ================= 性能与网络配置区 =================
    "MAX_WORKERS": 5,  # 并发处理的 APP 文件夹线程/app数。
    "MAX_VALID_SAMPLES_PER_APP": 5,  # 每个 APP 最多保留多少条 valid=True 的样本。
    # [No need to modify the following params]
    "LARGE_TRAJECTORY_THRESHOLD": 12,  # 选步数达到该阈值时，启用最小步距约束。
    "MIN_STEP_MARGIN": 2,  # 大轨迹下，已选样本之间的最小步距（按轨迹顺序索引计算）。
    "REQUEST_TIMEOUT": 120,  #  注意：视觉大模型（VLM）处理两张高分辨率图片速度较慢，建议保持 60 秒或以上。
    "MAX_RETRIES": 3,  # 单个任务失败（如网络抖动、API 暂时限流）时的最大重试次数。配合代码里的指数退避算法（等待 1, 2, 4 秒后重试）提升稳定性。
    # PROMPT
    "PROMPT": """
You are an expert AI data filter specializing in mobile GUI analysis. Your task is to evaluate GUI transition pairs and determine whether they are high-quality samples for training/evaluating an Inverse Dynamics Model (IDM). An IDM infers the action that causes the GUI state transition, given two consecutive screens as the input.

--------------------------------------------------

INPUT
You will receive:
[Screen 1]: The GUI state before the action
[Screen 2]: The GUI state after the action
[Action]: The user operation performed, including
(touch,intent,scroll,long_touch,set_text,kill_app,select,unselect,wait_user_login).
If [Action] includes a bounding box, [Screen 1] may contain a red overlay box highlighting that action region.

--------------------------------------------------

GLOBAL VISUAL RULES

- Ignore system status/navigation bar changes (time, battery, signal, etc.)
- Ignore dynamic updates incurred by ads refresh, timestamps, background feeds, etc.
- Focus ONLY on meaningful GUI changes within the app that are caused by the performed action
- Do NOT assume hidden steps or intermediate actions
- Do NOT infer invisible interactions; rely ONLY on visible UI evidence

--------------------------------------------------

EVALUATION PROCEDURE & RULES

Rely ONLY on visible UI evidence. Do not assume hidden steps. You MUST evaluate the sample against the following criteria and their associated violation rules. Check ALL rules; do not skip any.

1. Action Validity (action_valid)
The action must be a single, atomic interaction. Spatial Tolerance: It is VALID if the action area significantly overlaps with an interactable element, even if it includes surrounding empty space.

[Rule 1] Invalid Action: Action is missing, multi-step, ambiguous, targets elements not visible in Screen 1, or the action area is entirely on a blank background with no nearby elements.

2. Causal Correctness (causal_correct)
There must be a clear UI change that is the direct, logical result of the action.

[Rule 2] Home Screen Transition: Screen 1 is the mobile OS home screen (app launch), or Screen 2 is the home screen (app exit/crash).

[Rule 3] Illogical Mapping / No Result: The UI does not change, or the result violates standard mobile UI conventions (e.g., tap causes scroll, non-destructive action yields destructive warning, "three dots" doesn't open a menu).

[Rule 4] Unrelated Interference: The UI change is caused by ads, dynamic background feeds, low battery, or unrelated notifications. (Exception: OS-level permission dialogs directly triggered by the action are VALID).

3. IDM Learnability (idm_learnable)

The UI change must be stable, unambiguous, and meaningful for learning.

[Rule 5] Trivial Change: Screens are nearly identical. Changes are limited to ignored system bar updates (time/battery), cursor blinks, minor animations, or masked text (e.g., passwords as ***).

[Rule 6] Incomplete Rendering: Screen 2 shows loading spinners, skeleton screens, or is caught mid-transition.

[Rule 7] Invalid Scroll: A scroll action results in minimal, ambiguous, or inconsistent content displacement.

[Rule 8] Partial/Rotated Rendering Defect: Either screen is not fully/cleanly rendered (e.g., only part of the UI is visible after rotation, severe clipping/cropping, stretched layout, or obvious viewport mismatch that prevents reliable action-outcome judgment).

[Rule 9] Bounding Box Misalignment/Scale Error: For bbox-based actions, the highlighted bbox on Screen 1 is clearly wrong (e.g., too small/too large, shifted away from the actual target, or enclosing mostly irrelevant area), making the action target unreliable.

[Rule 10] Synthetic Auth/Text Placeholder Input: set_text uses synthetic placeholder text (e.g., dummy_user_input) on login/register/account-recovery/credential fields (email/phone/password/OTP/username), producing low-value or non-generalizable supervision.

[Rule 11] External/System Handoff: The transition is dominated by leaving the app flow or invoking OS/external surfaces (e.g., app chooser/open-with sheet, browser/social auth handoff, share sheet, external intent target), so the result is not a stable in-app causal outcome.

[Rule 12] Ambiguous Non-Atomic Target Node: The touched element is a generic text/container fragment (e.g., non-clickable child text, blank text node, broad informational paragraph) where the true interactive target is unclear.

[Rule 13] Degenerate Target Box Geometry: The action bbox is geometrically unreliable (e.g., tiny dot/line strip, extreme edge strip, or overly large region covering mostly irrelevant area), making target localization ambiguous.

[Rule 14] Scroll Without Coherent Displacement: A scroll action does not produce clear, directional content movement (or movement is negligible/contradictory), so the transition is not learnable as a scroll effect.

[Rule 15] Corrupted/Blank Visual Evidence: Screen 1 or Screen 2 is blank/black/corrupted/unreadable, preventing trustworthy visual grounding.

DECISION LOGIC & STRICT CONSISTENCY

If NO rules are triggered: valid = true, violations = [], and all criteria fields = true.
If ANY rule is triggered: valid = false, list ALL triggered rule IDs in violations.
Consistency: Criteria fields MUST be false if their corresponding rules are triggered:
- If Rule 1, 9, 12, or 13 triggered -> action_valid = false
- If Rule 2, 3, 4, or 11 triggered -> causal_correct = false
- If Rule 5, 6, 7, 8, 10, 14, or 15 triggered -> idm_learnable = false

OUTPUT FORMAT

Return a valid JSON object ONLY. Do NOT include markdown formatting (like ```json), explanations, or extra text.
{
    "valid": true | false,
    "criteria": {
    "action_valid": true | false,
    "causal_correct": true | false,
    "idm_learnable": true | false
    },
    "violations":[rule_ids],
    "reason": "1-2 concise sentences grounded in visible UI evidence."
}

A sample output looks like:
{
    "valid": false,
    "criteria": {
    "action_valid": true,
    "causal_correct": true,
    "idm_learnable": false
    },
    "violations":[6, 7],
    "reason": "..."
}
"""
}

# --- 日志配置 ---
logger = logging.getLogger(__name__)


def setup_logging():
    logger.setLevel(logging.DEBUG)
    if logger.hasHandlers():
        logger.handlers.clear()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    fh = logging.FileHandler(CONFIG["LOG_FILE"], mode='w', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)


# --- 函数区 ---

def encode_image(image_path):
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Reading image failed {image_path}: {e}")
        return None


def extract_bbox_from_action(action):
    if not isinstance(action, str):
        return None

    match = re.search(
        r"(?:bound_box|bounding_box|bbox)\s*=\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)",
        action,
        flags=re.IGNORECASE
    )
    if not match:
        return None

    x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if left == right or top == bottom:
        return None
    return left, top, right, bottom


def _render_image_with_bbox_overlay(image_path, bbox):
    from PIL import Image, ImageDraw

    with Image.open(image_path) as img:
        canvas = img.convert("RGB")
        width, height = canvas.size

        left, top, right, bottom = bbox
        left = max(0, min(left, width - 1))
        right = max(0, min(right, width - 1))
        top = max(0, min(top, height - 1))
        bottom = max(0, min(bottom, height - 1))
        if left >= right or top >= bottom:
            raise ValueError("Bounding box is outside image bounds or has invalid area.")

        rgba = canvas.convert("RGBA")
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        line_width = max(6, min(width, height) // 120)
        corner_len = max(20, line_width * 3)

        # Make target region easy to notice even on busy UIs.
        draw.rectangle([left, top, right, bottom], fill=(255, 0, 0, 45))

        # High-contrast double border.
        draw.rectangle([left, top, right, bottom], outline=(0, 0, 0, 255), width=line_width + 2)
        draw.rectangle([left, top, right, bottom], outline=(255, 0, 0, 255), width=line_width)

        # Corner marks.
        draw.line([(left, top), (left + corner_len, top)], fill=(255, 0, 0, 255), width=line_width)
        draw.line([(left, top), (left, top + corner_len)], fill=(255, 0, 0, 255), width=line_width)
        draw.line([(right, top), (right - corner_len, top)], fill=(255, 0, 0, 255), width=line_width)
        draw.line([(right, top), (right, top + corner_len)], fill=(255, 0, 0, 255), width=line_width)
        draw.line([(left, bottom), (left + corner_len, bottom)], fill=(255, 0, 0, 255), width=line_width)
        draw.line([(left, bottom), (left, bottom - corner_len)], fill=(255, 0, 0, 255), width=line_width)
        draw.line([(right, bottom), (right - corner_len, bottom)], fill=(255, 0, 0, 255), width=line_width)
        draw.line([(right, bottom), (right, bottom - corner_len)], fill=(255, 0, 0, 255), width=line_width)

        merged = Image.alpha_composite(rgba, overlay).convert("RGB")
        return merged, (left, top, right, bottom)


def encode_screen1_with_action_bbox(image_path, action):
    bbox = extract_bbox_from_action(action)
    if bbox is None:
        return encode_image(image_path), None

    try:
        merged, normalized_bbox = _render_image_with_bbox_overlay(image_path, bbox)
        buffer = BytesIO()
        merged.save(buffer, format="JPEG", quality=95)
        return base64.b64encode(buffer.getvalue()).decode("utf-8"), normalized_bbox
    except Exception as e:
        logger.warning(f"Failed to overlay bbox on Screen 1 ({image_path}): {e}. Falling back to original image.")
        return encode_image(image_path), None


def load_utg(utg_path):
    with open(utg_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"var\s+utg\s*=\s*", "", content)
    content = content.strip().rstrip(";")
    return json.loads(content)


def build_state_map(nodes):
    return {n['id']: n['image'] for n in nodes if n.get('id') and n.get('image')}


def extract_action(event):
    return f"{event.get('event_type', '')}: {event.get('event_str', '')}"


def should_process_event(event):
    """
    Event-level sampling filter. Return True to keep the event.
    Add new rules here when needed.
    """
    event_type = str(event.get("event_type", "")).strip().lower()

    blocked_event_types = {"intent", "kill_app", "wait_user_login"}
    if event_type in blocked_event_types:
        return False

    return True


def call_model(messages):
    import requests

    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            headers = {"Content-Type": "application/json"}
            if CONFIG["API_KEY"]:
                headers["Authorization"] = f"Bearer {CONFIG['API_KEY']}"
            response = requests.post(
                url=CONFIG["API_URL"],
                headers=headers,
                data=json.dumps({
                    "model": CONFIG["MODEL"],
                    "messages": messages,
                    "temperature": 0
                }),
                timeout=CONFIG["REQUEST_TIMEOUT"]
            )
            raw_response_text = response.text
            response.raise_for_status()
            response_data = response.json()
            usage = response_data.get("usage", {}) if isinstance(response_data, dict) else {}
            input_tokens = usage.get("prompt_tokens")
            if input_tokens is None:
                input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("completion_tokens")
            if output_tokens is None:
                output_tokens = usage.get("output_tokens")
            total_tokens = usage.get("total_tokens")
            if total_tokens is None and isinstance(input_tokens, int) and isinstance(output_tokens, int):
                total_tokens = input_tokens + output_tokens
            choices = response_data.get("choices", [])
            if not choices or "message" not in choices[0]:
                raise ValueError(f"Unexpected API response schema: {raw_response_text[:200]}")

            message_content = _content_to_text(choices[0]["message"].get("content"))
            return {
                "message_content": message_content,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }
        except Exception as e:
            logger.warning(f"API request failed (Attempt {attempt + 1}/{CONFIG['MAX_RETRIES']}): {e}")
            time.sleep(2 ** attempt)
    return None


def _content_to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return "\n".join(part for part in text_parts if part)
    return str(content) if content is not None else ""


def _normalize_json_text(raw_text):
    text = raw_text.strip()

    # Handle fenced output like ```json ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    json_match = re.search(r'\{[\s\S]*\}', text)
    candidate = json_match.group(0) if json_match else text

    # Some models output JSON-like booleans in uppercase.
    candidate = re.sub(r'\bTRUE\b', 'true', candidate)
    candidate = re.sub(r'\bFALSE\b', 'false', candidate)
    candidate = re.sub(r'\bNULL\b', 'null', candidate)
    candidate = re.sub(r'\bNone\b', 'null', candidate)
    return candidate


def parse_result(content):
    content_text = _content_to_text(content)
    if not content_text:
        return _error_result("API returned empty or request failed after retries")
    try:
        data = json.loads(_normalize_json_text(content_text))
        return {
            "valid": data.get("valid"),
            "action_valid": data.get("criteria", {}).get("action_valid"),
            "causal_correct": data.get("criteria", {}).get("causal_correct"),
            "idm_learnable": data.get("criteria", {}).get("idm_learnable"),
            "violations": str(data.get("violations", [])),
            "reason": data.get("reason", "No reason provided")
        }
    except Exception as e:
        return _error_result(f"Parse error: {e} | Content: {content_text[:150]}")


def _error_result(reason_str):
    return {
        "valid": None, "action_valid": None, "causal_correct": None,
        "idm_learnable": None, "violations": "error", "reason": reason_str
    }


def validate_task_input(task):
    from_img = task.get("from_img")
    to_img = task.get("to_img")
    action = task.get("action")

    if not from_img or not to_img:
        return "Input validation failed: both Screen 1 and Screen 2 paths are required."
    if not os.path.exists(from_img) or not os.path.exists(to_img):
        return "Input validation failed: Screen 1 or Screen 2 image file does not exist."
    if not isinstance(action, str) or not action.strip() or action.strip() == ":":
        return "Input validation failed: corresponding action is missing or empty."
    return None


def log_model_response_content(task, message_content, input_tokens=None, output_tokens=None, total_tokens=None):
    logger.debug(
        "Model response content | app=%s | from=%s | to=%s | action=%s | input_tokens=%s | output_tokens=%s | "
        "total_tokens=%s\n%s",
        task["app_name"],
        os.path.basename(task["from_img"]),
        os.path.basename(task["to_img"]),
        task["action"],
        input_tokens,
        output_tokens,
        total_tokens,
        message_content if message_content else "<empty-response>",
    )


def evaluate_transition(task):
    validation_error = validate_task_input(task)
    if validation_error:
        return {**task_to_row(task), **_error_result(validation_error)}

    img1_base64, bbox = encode_screen1_with_action_bbox(task['from_img'], task['action'])
    img2_base64 = encode_image(task['to_img'])
    if not img1_base64 or not img2_base64:
        return {**task_to_row(task), **_error_result("Image encoding failed")}
    if bbox is not None:
        logger.debug(
            "Applied bbox overlay on Screen 1 | app=%s | from=%s | bbox=%s",
            task.get("app_name", ""),
            os.path.basename(task['from_img']),
            bbox
        )
    content = [
        {"type": "text",
         "text": "I will provide two images. IMAGE 1 is the state BEFORE the action. IMAGE 2 is the state AFTER the action."},
        {"type": "text", "text": "### START OF IMAGE 1 (BEFORE) ###"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img1_base64}"}},
        {"type": "text", "text": "### END OF IMAGE 1 ###"},
        {"type": "text", "text": "### START OF IMAGE 2 (AFTER) ###"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img2_base64}"}},
        {"type": "text", "text": "### END OF IMAGE 2 ###"},
        {"type": "text", "text": f"ACTION: {task['action']}"},
        {"type": "text", "text": CONFIG["PROMPT"]}
    ]
    messages = [{"role": "user", "content": content}]
    model_result = call_model(messages)
    final_content = model_result.get("message_content", "") if model_result else ""
    input_tokens = model_result.get("input_tokens") if model_result else None
    output_tokens = model_result.get("output_tokens") if model_result else None
    total_tokens = model_result.get("total_tokens") if model_result else None
    log_model_response_content(task, final_content, input_tokens, output_tokens, total_tokens)
    parsed = parse_result(final_content)
    return {**task_to_row(task), **parsed}


def task_to_row(task):
    return {
        "app_name": task['app_name'],
        "from_screen_filename": os.path.basename(task['from_img']),
        "to_screen_filename": os.path.basename(task['to_img']),
        "action": task['action']
    }


def load_processed_tasks(csv_path):
    if not os.path.exists(csv_path):
        return set(), {}

    processed_ids = set()
    valid_true_count_by_app = {}
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not all(k in row for k in ['app_name', 'from_screen_filename', 'to_screen_filename', 'action']):
                    continue

                valid_str = str(row.get('valid', '')).strip().lower()
                is_successful = row.get('violations') != 'error' and valid_str in {'true', 'false'}
                if not is_successful:
                    continue

                task_id = (
                    row['app_name'],
                    row['from_screen_filename'],
                    row['to_screen_filename'],
                    row['action']
                )
                processed_ids.add(task_id)

                if valid_str == 'true':
                    app_name = row['app_name']
                    valid_true_count_by_app[app_name] = valid_true_count_by_app.get(app_name, 0) + 1
    except Exception as e:
        logger.error(f"Error reading existing CSV file at {csv_path}: {e}. Continuing without resuming.")
        return set(), {}

    logger.info(f"Loaded {len(processed_ids)} previously processed tasks from {csv_path}. They will be skipped.")
    return processed_ids, valid_true_count_by_app


def _is_true_string(value):
    return str(value or "").strip().lower() == "true"


def _row_task_key(row):
    return (
        str(row.get("app_name", "")).strip(),
        str(row.get("from_screen_filename", "")).strip(),
        str(row.get("to_screen_filename", "")).strip(),
        str(row.get("action", "")).strip(),
    )


def _build_task_from_csv_row(row):
    app_name = str(row.get("app_name", "")).strip()
    from_name = str(row.get("from_screen_filename", "")).strip()
    to_name = str(row.get("to_screen_filename", "")).strip()
    action = str(row.get("action", "")).strip()
    return {
        "app_name": app_name,
        "from_img": os.path.join(CONFIG["ROOT_DIR"], app_name, "states", from_name),
        "to_img": os.path.join(CONFIG["ROOT_DIR"], app_name, "states", to_name),
        "action": action,
    }


def refilter_existing_valid_csv(csv_path, max_workers):
    required = {"app_name", "from_screen_filename", "to_screen_filename", "action", "valid"}
    update_fields = ["valid", "action_valid", "causal_correct", "idm_learnable", "violations", "reason"]

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if not required.issubset(set(fieldnames)):
            missing = sorted(required - set(fieldnames))
            logger.warning(
                f"Existing CSV missing required columns for re-filter mode: {missing}. "
                f"Falling back to full trace-folder filtering."
            )
            return False
        rows = list(reader)

    if not rows:
        logger.warning("Existing CSV is empty. Falling back to full trace-folder filtering.")
        return False

    for col in update_fields:
        if col not in fieldnames:
            fieldnames.append(col)

    # Keep one task per unique key, only from rows that were valid=True in previous round.
    seen_keys = set()
    valid_rows = []
    for row in rows:
        key = _row_task_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if _is_true_string(row.get("valid")):
            valid_rows.append(row)

    if not valid_rows:
        logger.info("No valid=True rows found in existing CSV. Nothing to re-filter.")
        return True

    tasks = [_build_task_from_csv_row(row) for row in valid_rows]
    results = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        future_to_idx = {executor.submit(evaluate_transition, task): idx for idx, task in enumerate(tasks)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            task = tasks[idx]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {**task_to_row(task), **_error_result(f"Unexpected refilter error: {e}")}

    result_map = {_row_task_key(row): row for row in results if row is not None}

    updated_rows = []
    round2_valid = 0
    round2_invalid = 0
    round2_error = 0
    changed_count = 0

    for row in rows:
        key = _row_task_key(row)
        if _is_true_string(row.get("valid")) and key in result_map:
            prev_valid = str(row.get("valid", ""))
            updated = dict(row)
            round2 = result_map[key]
            for col in update_fields:
                updated[col] = round2.get(col, updated.get(col, ""))
            if str(updated.get("valid", "")) != prev_valid:
                changed_count += 1
            valid_value = str(updated.get("valid", "")).strip().lower()
            if valid_value == "true":
                round2_valid += 1
            elif valid_value == "false":
                round2_invalid += 1
            else:
                round2_error += 1
            updated_rows.append(updated)
        else:
            updated_rows.append(row)

    backup_path = f"{csv_path}.backup_before_refilter_{time.strftime('%Y%m%d_%H%M%S')}"
    os.replace(csv_path, backup_path)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    logger.info(">>> Re-filter mode completed using existing valid=True samples only.")
    logger.info(f"Input/Output CSV: {csv_path}")
    logger.info(f"Backup created: {backup_path}")
    logger.info(f"Round-1 valid selected: {len(valid_rows)}")
    logger.info(f"Round-2 valid: {round2_valid}")
    logger.info(f"Round-2 invalid: {round2_invalid}")
    logger.info(f"Round-2 error: {round2_error}")
    logger.info(f"Rows changed from prior valid=True status: {changed_count}")
    return True


def main(max_workers=None):
    setup_logging()

    if max_workers is None:
        max_workers = CONFIG["MAX_WORKERS"]
    if max_workers <= 0:
        logger.warning(f"Ignoring invalid --max-workers={max_workers}. Using 1.")
        max_workers = 1

    fieldnames = [
        "app_name", "from_screen_filename", "to_screen_filename", "action",
        "valid", "action_valid", "causal_correct", "idm_learnable",
        "violations", "reason"
    ]
    output_csv_path = CONFIG["OUTPUT_CSV"]
    refilter_input_csv_path = str(CONFIG.get("REFILTER_INPUT_CSV", "")).strip()
    if not refilter_input_csv_path:
        refilter_input_csv_path = output_csv_path

    # Auto mode switch:
    # - If REFILTER_INPUT_CSV exists and is non-empty: only re-validate previous valid=True rows in that CSV.
    # - Otherwise: run original full trace-folder filtering logic.
    if os.path.exists(refilter_input_csv_path) and os.path.getsize(refilter_input_csv_path) > 0:
        logger.info(
            f">>> Existing CSV detected at {refilter_input_csv_path}. "
            "Entering re-filter mode (only prior valid=True rows)."
        )
        if refilter_existing_valid_csv(refilter_input_csv_path, max_workers):
            return

    processed_ids, valid_true_count_by_app = load_processed_tasks(output_csv_path)
    logger.info(">>> Scanning directories and evaluating sampled transitions...")

    need_header = not os.path.exists(output_csv_path) or os.path.getsize(output_csv_path) == 0

    app_names = []
    for app_name in os.listdir(CONFIG["ROOT_DIR"]):
        app_path = os.path.join(CONFIG["ROOT_DIR"], app_name)
        if os.path.exists(os.path.join(app_path, "utg.js")):
            app_names.append(app_name)

    def process_single_app(app_name):
        app_path = os.path.join(CONFIG["ROOT_DIR"], app_name)
        utg_path = os.path.join(app_path, "utg.js")

        already_valid_true = valid_true_count_by_app.get(app_name, 0)
        app_valid_quota = max(0, CONFIG["MAX_VALID_SAMPLES_PER_APP"] - already_valid_true)
        if app_valid_quota <= 0:
            return {
                "app_name": app_name,
                "rows": [],
                "total_found": 0,
                "skipped_filter": 0,
                "candidates": 0,
                "evaluated": 0,
                "valid_added": 0,
                "skipped_quota": True,
                "error": None,
            }

        try:
            utg = load_utg(utg_path)
        except Exception as e:
            return {
                "app_name": app_name,
                "rows": [],
                "total_found": 0,
                "skipped_filter": 0,
                "candidates": 0,
                "evaluated": 0,
                "valid_added": 0,
                "skipped_quota": False,
                "error": str(e),
            }

        state_map = build_state_map(utg.get("nodes", []))
        app_candidates = []
        app_total_found = 0
        app_skipped_filter = 0
        scan_step = 0
        seen_task_ids = set()

        for edge in utg.get("edges", []):
            from_id, to_id, events = edge.get("from"), edge.get("to"), edge.get("events", [])
            if not all([from_id, to_id, events]) or from_id not in state_map or to_id not in state_map:
                continue

            from_img_path = os.path.join(app_path, state_map[from_id])
            to_img_path = os.path.join(app_path, state_map[to_id])
            if not (os.path.exists(from_img_path) and os.path.exists(to_img_path)):
                continue

            for event in events:
                scan_step += 1
                if not should_process_event(event):
                    app_skipped_filter += 1
                    continue

                app_total_found += 1
                action_str = extract_action(event)
                from_img_filename = os.path.basename(from_img_path)
                to_img_filename = os.path.basename(to_img_path)
                task_id = (app_name, from_img_filename, to_img_filename, action_str)
                if task_id in processed_ids or task_id in seen_task_ids:
                    continue
                seen_task_ids.add(task_id)

                event_id = event.get("event_id")
                try:
                    trajectory_step = int(event_id)
                except (TypeError, ValueError):
                    trajectory_step = scan_step

                app_candidates.append({
                    "app_name": app_name,
                    "from_img": from_img_path,
                    "to_img": to_img_path,
                    "action": action_str,
                    "trajectory_step": trajectory_step,
                    "scan_step": scan_step,
                })

        app_candidates.sort(key=lambda t: (t["trajectory_step"], t["scan_step"]))
        for idx, task in enumerate(app_candidates):
            task["trajectory_index"] = idx

        if not app_candidates:
            return {
                "app_name": app_name,
                "rows": [],
                "total_found": app_total_found,
                "skipped_filter": app_skipped_filter,
                "candidates": 0,
                "evaluated": 0,
                "valid_added": 0,
                "skipped_quota": False,
                "error": None,
            }

        large_trajectory = len(app_candidates) >= CONFIG["LARGE_TRAJECTORY_THRESHOLD"]
        min_step_margin = CONFIG["MIN_STEP_MARGIN"] if large_trajectory else 0

        mid = len(app_candidates) // 2
        sample_order_indices = [mid]
        offset = 1
        while len(sample_order_indices) < len(app_candidates):
            left = mid - offset
            right = mid + offset
            if left >= 0:
                sample_order_indices.append(left)
            if right < len(app_candidates):
                sample_order_indices.append(right)
            offset += 1

        rows = []
        app_valid_added = 0
        app_evaluated = 0
        selected_positions = []
        per_app_in_flight = max(1, min(CONFIG["MAX_VALID_SAMPLES_PER_APP"], app_valid_quota))
        next_order_pos = 0

        while next_order_pos < len(sample_order_indices):
            if app_valid_added >= app_valid_quota:
                break

            batch_items = []
            while next_order_pos < len(sample_order_indices) and len(batch_items) < per_app_in_flight:
                idx = sample_order_indices[next_order_pos]
                next_order_pos += 1
                task = app_candidates[idx]
                if min_step_margin > 0 and any(
                    abs(task["trajectory_index"] - pos) < min_step_margin for pos in selected_positions
                ):
                    continue
                batch_items.append((idx, task))

            if not batch_items:
                continue

            if len(batch_items) == 1:
                idx, task = batch_items[0]
                evaluated_batch = [(idx, task, evaluate_transition(task))]
            else:
                with ThreadPoolExecutor(max_workers=len(batch_items)) as app_executor:
                    future_to_meta = {
                        app_executor.submit(evaluate_transition, task): (idx, task)
                        for idx, task in batch_items
                    }
                    done_results = {}
                    for future in as_completed(future_to_meta):
                        idx, task = future_to_meta[future]
                        try:
                            row_result = future.result()
                        except Exception as e:
                            row_result = {**task_to_row(task), **_error_result(f"Unexpected app-batch error: {e}")}
                        done_results[idx] = (task, row_result)

                evaluated_batch = []
                for idx, _ in batch_items:
                    task, row_result = done_results[idx]
                    evaluated_batch.append((idx, task, row_result))

            for _, task, row_result in evaluated_batch:
                rows.append(row_result)
                app_evaluated += 1

                if row_result.get("valid") is True:
                    if min_step_margin > 0 and any(
                        abs(task["trajectory_index"] - pos) < min_step_margin for pos in selected_positions
                    ):
                        continue
                    app_valid_added += 1
                    selected_positions.append(task["trajectory_index"])
                    if app_valid_added >= app_valid_quota:
                        break

        return {
            "app_name": app_name,
            "rows": rows,
            "total_found": app_total_found,
            "skipped_filter": app_skipped_filter,
            "candidates": len(app_candidates),
            "evaluated": app_evaluated,
            "valid_added": app_valid_added,
            "skipped_quota": False,
            "error": None,
            "large_trajectory": large_trajectory,
            "min_step_margin": min_step_margin,
            "quota": app_valid_quota,
        }

    total_found = 0
    total_skipped_by_event_filter = 0
    total_candidates = 0
    total_evaluated = 0
    stats_valid = 0
    stats_invalid = 0
    stats_error = 0

    with open(output_csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if need_header:
            writer.writeheader()
            f.flush()

        def consume_app_result(result):
            nonlocal total_found, total_skipped_by_event_filter, total_candidates
            nonlocal total_evaluated, stats_valid, stats_invalid, stats_error

            app_name = result["app_name"]
            if result.get("error"):
                logger.error(f"Failed to process {app_name}: {result['error']}")
                return

            total_found += result["total_found"]
            total_skipped_by_event_filter += result["skipped_filter"]
            total_candidates += result["candidates"]

            if result.get("skipped_quota"):
                logger.info(
                    f"[{app_name}] already has {valid_true_count_by_app.get(app_name, 0)} valid samples "
                    f"(quota reached), skipping."
                )
                return

            if result["candidates"] > 0:
                logger.info(
                    f"[{app_name}] candidates={result['candidates']}, quota={result.get('quota', 0)}, "
                    f"large_trajectory={result.get('large_trajectory', False)}, "
                    f"min_step_margin={result.get('min_step_margin', 0)}"
                )

            for row in result["rows"]:
                writer.writerow(row)
                valid_value = row.get("valid")
                if valid_value is True:
                    stats_valid += 1
                elif valid_value is False:
                    stats_invalid += 1
                else:
                    stats_error += 1

            total_evaluated += result["evaluated"]
            logger.info(f"[{app_name}] evaluated={result['evaluated']}, new_valid_true={result['valid_added']}")

        if max_workers == 1:
            for app_name in app_names:
                result = process_single_app(app_name)
                consume_app_result(result)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                app_iter = iter(app_names)
                in_flight = {}
                max_in_flight = max_workers * 4

                for _ in range(max_in_flight):
                    app_name = next(app_iter, None)
                    if app_name is None:
                        break
                    future = executor.submit(process_single_app, app_name)
                    in_flight[future] = app_name

                while in_flight:
                    finished = next(as_completed(in_flight))
                    in_flight.pop(finished)
                    try:
                        result = finished.result()
                    except Exception as e:
                        logger.error(f"A folder task failed with unexpected error: {e}")
                        continue

                    consume_app_result(result)

                    next_app = next(app_iter, None)
                    if next_app is not None:
                        future = executor.submit(process_single_app, next_app)
                        in_flight[future] = next_app

    if total_evaluated == 0:
        logger.warning("No new tasks were evaluated in this run.")
        return

    logger.info("\n" + "=" * 20 + " This Run's Stats " + "=" * 20)
    logger.info(f"  Total eligible events found: {total_found}")
    logger.info(f"  Skipped by event filters:   {total_skipped_by_event_filter}")
    logger.info(f"  New candidates considered:  {total_candidates}")
    logger.info(f"  API calls in this run:      {total_evaluated}")
    logger.info(f"  Valid Transitions:          {stats_valid} ({(stats_valid / total_evaluated):.2%})")
    logger.info(f"  Invalid Transitions:        {stats_invalid} ({(stats_invalid / total_evaluated):.2%})")
    logger.info(f"  Processing Errors:          {stats_error} ({(stats_error / total_evaluated):.2%})")
    logger.info("=" * 58)
    logger.info(f"Results have been appended to {CONFIG['OUTPUT_CSV']}")
    logger.info(f"Full execution log saved to {CONFIG['LOG_FILE']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter mobile GUI transitions for IDM.")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=CONFIG["MAX_WORKERS"],
        help="Max number of folder-processing threads."
    )
    args = parser.parse_args()
    main(max_workers=args.max_workers)
