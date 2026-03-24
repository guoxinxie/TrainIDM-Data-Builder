import os
import json
import csv
import base64
import requests
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from tqdm import tqdm

# --- 配置区 ---
CONFIG = {
    # ================= 路径配置区 =================
    "ROOT_DIR": "/data/mv_trace_en",  # 输入端：原始数据集的根目录。程序会遍历该目录下的各个 APP 文件夹读取 utg.js 和截图
    "OUTPUT_CSV": "/data/filter_mv_trace.csv",  # 输出端：模型评估结果的保存路径。支持断点续传，已存在的数据会自动跳过
    "LOG_FILE": "/data/filter_mv_trace.log",  # 日志端：运行日志保存路径，用于排查报错（如 API 异常、图片读取失败等）

    # ================= 大模型 API 配置区 =================
    # 支持任何兼容 OpenAI 接口格式的服务（如 OpenRouter、本地部署的 vLLM、Ollama 等）
    "API_KEY": "YOUR_API_KEY",  # 你的 API 密钥。如果使用的是本地部署的 vLLM 等无鉴权服务，保持为空字符串即可
    "API_URL": "https://openrouter.ai/api/v1/chat/completions",
    # API 请求地址。若使用本地 vLLM，通常改为 "http://localhost:8000/v1/chat/completions"
    "MODEL": "qwen/qwen3.5-397b-a17b",  # 调用的具体视觉模型名称。必须与提供商（或本地部署）的模型列表名称严格一致

    # ================= 性能与网络配置区 =================
    "MAX_WORKERS": 10,  # 多线程并发数。
    "REQUEST_TIMEOUT": 120,
    #  注意：视觉大模型（VLM）处理两张高分辨率图片速度较慢，建议保持 60 秒或以上。
    "MAX_RETRIES": 3,  # 单个任务失败（如网络抖动、API 暂时限流）时的最大重试次数。配合代码里的指数退避算法（等待 1, 2, 4 秒后重试）提升稳定性。
    # PROMPT
    "PROMPT": """
ROLE & TASK
You are an expert AI data filter specializing in mobile GUI analysis. Your task is to evaluate GUI transition pairs and determine whether they are high-quality samples for training/evaluating an Inverse Dynamics Model (IDM).

An IDM learns:
(Screen 1, Screen 2) → Action

Your goal is to STRICTLY retain only clean, causal, semantically correct, and visually learnable interactions.

--------------------------------------------------

INPUT
You will receive:
[Screen 1]: The GUI state before the action
[Screen 2]: The GUI state after the action
[Action]: The user operation performed
(touch,intent,scroll,long_touch,set_text,kill_app,select,unselect,wait_user_login).

--------------------------------------------------

GLOBAL VISUAL RULES

- Ignore system status/navigation bar changes (time, battery, signal, etc.)
- Ignore minor dynamic updates (ads refresh, timestamps, background feeds)
- Focus ONLY on meaningful UI changes within the app
- Do NOT assume hidden steps or intermediate actions
- Do NOT infer invisible interactions; rely ONLY on visible UI evidence

--------------------------------------------------
EVALUATION PROCEDURE (MANDATORY)

You MUST follow this exact order:

Step 1: Evaluate the three criteria (action_valid, causal_correct, idm_learnable)

Step 2: Independently check ALL violation rules (Rule 1–8), do NOT skip any rule

Step 3: If ANY rule is triggered → valid = FALSE

Step 4: Ensure criteria fields are consistent with triggered violations

Do NOT skip Step 2 even if the sample appears valid.

--------------------------------------------------
PART 1: WHAT WE NEED (POSITIVE CRITERIA)

A VALID sample MUST satisfy ALL of the following:

1. Action Validity (action_valid)
- The action is a single, atomic interaction (NOT a sequence).
- The action targets a visible and interactable UI element in Screen 1.
- **Spatial Tolerance:** The targeted region (bounding box/coordinates) may be larger than the actual visual icon or text due to invisible touch padding. As long as a clear interactable element (like an icon, button, or input field) is present within, or significantly overlaps with the targeted region, it is considered VALID. Do not reject it just because the action area includes some empty space around the icon.

2. Causal Correctness (causal_correct)
- A clear UI change exists between Screen 1 and Screen 2
- The change is the direct and immediate result of the action
- The transition follows common mobile UI interaction conventions

3. IDM Learnability (idm_learnable)
- The UI change is meaningful and non-trivial
- Screen 2 is fully rendered, stable, and not mid-transition
- The mapping from action → visual result is clear and unambiguous

--------------------------------------------------

PART 2: WHAT WE MUST FILTER OUT (NEGATIVE RULES)

If ANY rule below is triggered → the sample is INVALID

[Rule 1] Action Error
- Action is missing, empty, or None
- Action contains multiple steps (not atomic)
- Action targets elements not visible in Screen 1 (temporal mismatch)
- Action area is ENTIRELY on a blank background with NO interactable elements inside or near it.
- Action target is ambiguous or not clearly identifiable

[Rule 2] No Home Screen Transitions
- Screen 1 is the mobile OS home/launcher screen (app launch)
- Screen 2 is the home screen (app exit, crash, or go-home action)

[Rule 3] Unnatural Mapping / Semantic Mismatch
- The result violates common mobile UI interaction conventions
- The action-result mapping is illogical, highly unusual, or unlikely in real apps

Examples:
- "More options" (three-dot menu) does NOT open a menu
- A non-destructive action triggers a destructive confirmation dialog
- A standard UI element leads to an unrelated function

IMPORTANT:
If the mapping is highly unusual or contradicts standard UI behavior, mark INVALID even if a UI change exists

[Rule 4] Action Failure / Illogical Result
- The UI does not change after the action
- The result is logically inconsistent with the action
- Example: tap causes scroll, or one tap updates multiple unrelated components

[Rule 5] System or Background Interference
- OS-level UI appears (permission dialogs, system alerts, notifications)
- UI changes due to unrelated external/background events

[Rule 6] No Meaningful Change / Unlearnable Feedback
- Screen 1 and Screen 2 are nearly identical
- Only trivial differences (cursor blink, minor animation, tiny shifts)
- Changes are not meaningful for learning action-to-UI mapping
- Masked or hidden content (e.g., passwords shown as ***)

[Rule 7] Incomplete Rendering
- Screen 2 shows loading states, spinners, skeleton screens, or blank UI
- UI is not fully rendered or stable

[Rule 8] Invalid Scroll
- Scroll action does not produce clear and consistent content displacement
- Movement is minimal, ambiguous, or inconsistent

--------------------------------------------------

DECISION LOGIC

- If NO rules are triggered:
  valid = TRUE
  violations = []

- If ANY rule is triggered:
  valid = FALSE
  violations must include ALL matched rule IDs (e.g., [3], [1, 4])

--------------------------------------------------

CRITERIA CONSISTENCY RULE (STRICT)

The criteria fields MUST align with violations:

- If Rule 1 triggered → action_valid = FALSE
- If Rule 3, 4, or 5 triggered → causal_correct = FALSE
- If Rule 6, 7, or 8 triggered → idm_learnable = FALSE

If no rule is triggered → all criteria must be TRUE

--------------------------------------------------

CRITICAL OUTPUT FORMAT

You MUST return a valid JSON object ONLY.
Do NOT include markdown, explanations, or extra text.

{
  "valid": TRUE or FALSE,
  "criteria": {
    "action_valid": TRUE or FALSE,
    "causal_correct": TRUE or FALSE,
    "idm_learnable": TRUE or FALSE
  },
  "violations": [],
  "reason": "A concise 1-3 sentence explanation referencing visible UI evidence"
}

--------------------------------------------------

FINAL INSTRUCTION

Be strict, conservative, and precise.
Only retain high-confidence, semantically correct, and learnable samples.
If anything is ambiguous, unusual, or weakly justified → mark INVALID.

"""

}

# --- 日志配置 ---
logger = logging.getLogger(__name__)


def setup_logging():
    logger.setLevel(logging.INFO)
    if logger.hasHandlers():
        logger.handlers.clear()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    fh = logging.FileHandler(CONFIG["LOG_FILE"], mode='w', encoding='utf-8')
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


def call_model(messages):
    for attempt in range(CONFIG["MAX_RETRIES"]):
        try:
            headers = {"Content-Type": "application/json"}
            if CONFIG["API_KEY"]:
                headers["Authorization"] = f"Bearer {CONFIG['API_KEY']}"
            response = requests.post(
                url=CONFIG["API_URL"],
                headers=headers,
                data=json.dumps({"model": CONFIG["MODEL"], "messages": messages}),
                timeout=CONFIG["REQUEST_TIMEOUT"]
            )
            response.raise_for_status()
            return response.json()['choices'][0]['message']
        except Exception as e:
            logger.warning(f"API request failed (Attempt {attempt + 1}/{CONFIG['MAX_RETRIES']}): {e}")
            time.sleep(2 ** attempt)
    return None


def parse_result(content):
    if not content:
        return _error_result("API returned empty or request failed after retries")
    try:
        json_match = re.search(r'\{[\s\S]*\}', content)
        content_to_parse = json_match.group(0) if json_match else content
        data = json.loads(content_to_parse)
        return {
            "valid": data.get("valid"),
            "action_valid": data.get("criteria", {}).get("action_valid"),
            "causal_correct": data.get("criteria", {}).get("causal_correct"),
            "idm_learnable": data.get("criteria", {}).get("idm_learnable"),
            "violations": str(data.get("violations", [])),
            "reason": data.get("reason", "No reason provided")
        }
    except Exception as e:
        return _error_result(f"Parse error: {e} | Content: {content[:150]}")


def _error_result(reason_str):
    return {
        "valid": None, "action_valid": None, "causal_correct": None,
        "idm_learnable": None, "violations": "error", "reason": reason_str
    }


def evaluate_transition(task):
    img1_base64 = encode_image(task['from_img'])
    img2_base64 = encode_image(task['to_img'])
    if not img1_base64 or not img2_base64:
        return {**task_to_row(task), **_error_result("Image encoding failed")}
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
    res = call_model(messages)
    final_content = res.get("content") if res and res.get("content") else ""
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
        return set()

    processed_ids = set()
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 确保关键列存在
                if all(k in row for k in ['app_name', 'from_screen_filename', 'to_screen_filename', 'action']):
                    task_id = (
                        row['app_name'],
                        row['from_screen_filename'],
                        row['to_screen_filename'],
                        row['action']
                    )
                    processed_ids.add(task_id)
    except Exception as e:
        logger.error(f"Error reading existing CSV file at {csv_path}: {e}. Continuing without resuming.")
        return set()

    logger.info(f"Loaded {len(processed_ids)} previously processed tasks from {csv_path}. They will be skipped.")
    return processed_ids


def main():
    #  初始化日志
    setup_logging()

    processed_ids = load_processed_tasks(CONFIG["OUTPUT_CSV"])

    logger.info(">>> Scanning directories and collecting new tasks...")
    tasks = []
    total_found = 0

    for app_name in os.listdir(CONFIG["ROOT_DIR"]):
        app_path = os.path.join(CONFIG["ROOT_DIR"], app_name)
        utg_path = os.path.join(app_path, "utg.js")
        if not os.path.exists(utg_path):
            continue

        try:
            utg = load_utg(utg_path)
            state_map = build_state_map(utg.get("nodes", []))
            for edge in utg.get("edges", []):
                from_id, to_id, events = edge.get("from"), edge.get("to"), edge.get("events", [])
                if not all([from_id, to_id, events]) or from_id not in state_map or to_id not in state_map:
                    continue

                from_img_path = os.path.join(app_path, state_map[from_id])
                to_img_path = os.path.join(app_path, state_map[to_id])
                if not (os.path.exists(from_img_path) and os.path.exists(to_img_path)):
                    continue

                for event in events:
                    total_found += 1
                    action_str = extract_action(event)
                    from_img_filename = os.path.basename(from_img_path)
                    to_img_filename = os.path.basename(to_img_path)

                    task_id = (app_name, from_img_filename, to_img_filename, action_str)

                    if task_id not in processed_ids:
                        tasks.append({
                            "app_name": app_name,
                            "from_img": from_img_path,
                            "to_img": to_img_path,
                            "action": action_str
                        })

        except Exception as e:
            logger.error(f"Failed to process {app_name}: {e}")

    new_tasks_count = len(tasks)
    if new_tasks_count == 0:
        logger.warning(
            f"Scan complete. Found {total_found} total possible tasks, but all have been processed. Exiting.")
        return

    logger.info(
        f"Found {total_found} total possible tasks. After filtering, {new_tasks_count} new tasks will be processed.")

    results_for_stats = []
    csv_lock = threading.Lock()
    fieldnames = [
        "app_name", "from_screen_filename", "to_screen_filename", "action",
        "valid", "action_valid", "causal_correct", "idm_learnable",
        "violations", "reason"
    ]

    # === 修改核心区域开始 ===
    output_csv_path = CONFIG["OUTPUT_CSV"]
    # 检查文件是否不存在，或者文件存在但大小为0（空文件）
    need_header = not os.path.exists(output_csv_path) or os.path.getsize(output_csv_path) == 0

    with open(output_csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        # 如果需要表头，则写入
        if need_header:
            writer.writeheader()
            f.flush()  # 强制立即将表头写入磁盘，防止多线程写入时发生覆盖或错乱
        # === 修改核心区域结束 ===

        with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
            futures = [executor.submit(evaluate_transition, task) for task in tasks]
            pbar = tqdm(as_completed(futures), total=new_tasks_count, desc="Evaluating New Transitions", unit="task")

            for future in pbar:
                try:
                    row_result = future.result()
                    results_for_stats.append(row_result)
                    with csv_lock:
                        writer.writerow(row_result)
                    status = (
                        " Valid" if row_result.get("valid")
                        else " Invalid" if row_result.get("valid") is FALSE
                        else " Error"
                    )
                    pbar.set_postfix_str(status)
                except Exception as e:
                    logger.error(f"A task failed with an unexpected error: {e}")

    # 3. 最终统计
    stats_valid = sum(1 for r in results_for_stats if r.get("valid"))
    stats_invalid = sum(1 for r in results_for_stats if r.get("valid") is FALSE)
    stats_error = new_tasks_count - stats_valid - stats_invalid

    # --- 日志输出部分 ---
    logger.info("\n" + "=" * 20 + " This Run's Stats " + "=" * 20)
    logger.info(f"  Tasks Processed in this run: {new_tasks_count}")
    logger.info(
        f"  Valid Transitions:   {stats_valid} ({(stats_valid / new_tasks_count if new_tasks_count > 0 else 0):.2%})")
    logger.info(
        f"  Invalid Transitions: {stats_invalid} ({(stats_invalid / new_tasks_count if new_tasks_count > 0 else 0):.2%})")
    logger.info(
        f"   Processing Errors:   {stats_error} ({(stats_error / new_tasks_count if new_tasks_count > 0 else 0):.2%})")
    logger.info("=" * 58)

    logger.info(f"Results have been appended to {CONFIG['OUTPUT_CSV']}")
    logger.info(f"Full execution log saved to {CONFIG['LOG_FILE']}")


if __name__ == "__main__":
    main()
