import os
import json
import csv
import time
import base64
import requests
import re
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ==========================
# 配置
# ==========================

FILTERED_ROOT = "/data/screenshots_jp"
SCREENSHOT_ROOT = "/data/screenshots_jp"
OUTPUT_CSV = "/data/gui_transition_result.csv"

MAX_SAMPLES = None
MAX_WORKERS = 10

RETRY = 10
RETRY_BASE_SLEEP = 2

API_KEY = os.environ.get("OPENROUTER_API_KEY",
                         "")

MODEL = "google/gemini-3.1-flash-lite-preview"

PROMPT = """
### ROLE
You are a Strict UI Trace Auditor. You evaluate if the SINGLE gesture (Tap or Swipe) shown in IMAGE 1 is the SOLE and DIRECT cause of the change in IMAGE 2.

### 1. ACTION IDENTIFICATION (CRITICAL):
- In IMAGE 1, look for the action marker:
  - **TAP**: Usually a single dot.
  - **SWIPE/SCROLL**: Usually a line connecting two dots (e.g., Red start dot -> Blue line -> Green end dot).

### 2. THE "IMPOSSIBLE JUMP" RULE:
- **Form Fields**: A single tap on one input line CANNOT fill multiple separate fields simultaneously (unless it hit an 'Auto-fill' button).
- **Scrolling**: If the action is a TAP on a blank space, it CANNOT cause the screen to scroll. However, if the action is a SWIPE (line indicator), a scrolling change in IMAGE 2 is VALID and EXPECTED.

### 3. EVALUATION STEPS:
**Step 1: Analyze IMAGE 1 ONLY.**
- Identify the EXACT visual element under the action marker. DO NOT guess intent.
- Describe the action type (e.g., Tap, Swipe).
- **Your Observation for Image 1:** [Model must fill this in first]

**Step 2: Analyze IMAGE 2 ONLY.**
- Describe the main change compared to Image 1. Which element is now active or what new screen is shown?
- **Your Observation for Image 2:** [Model must fill this in first]

**Step 3: Compare and Conclude.**
- Based ONLY on your observations from Step 1 and 2, is the transition logical?
- If Observation 1 (e.g., Tap on 'SERVICES') directly leads to Observation 2 (e.g., 'INBOX' page is shown), this is a contradiction. You MUST classify it as an error.

### 4. CLASSIFICATION:
- "none": Valid gesture -> Expected logical result.
- "accidental_touch": 
    1. Tap hit background/dead-zone but UI changed dramatically.
    2. Tap hit an input line but whole form got filled.
    3. Action completely unrelated to the result.

### 5. OUTPUT:
{
  "continuous": false (if mismatch or miss) | true,
  "error_type": "none | accidental_touch | no_transition",
  "reason": "1. Gesture was a [Tap on X / Swipe in Y area]. 2. Image 2 showed [Change]. 3. Logic: Explain why this gesture can or cannot cause this change."
}
"""

# ==========================
# 日志系统
# ==========================

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/run.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

error_logger = logging.getLogger("error")
error_handler = logging.FileHandler("logs/error.log")
error_logger.addHandler(error_handler)

# ==========================
# 全局变量
# ==========================

csv_lock = threading.Lock()
progress_lock = threading.Lock()

global_completed = 0
global_total = 0
global_success = 0
global_failed = 0
global_api_errors = 0

# ==========================
# HTTP Session（连接复用）
# ==========================

session = requests.Session()

session.headers.update({
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
})


# ==========================
# Base64编码
# ==========================

def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ==========================
# 调用模型
# ==========================

def analyze_ui_transition(img1, img2):
    img1_base64 = encode_image(img1)
    img2_base64 = encode_image(img2)

    payload = {
        "model": MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text",
                     "text": "I will provide two images. IMAGE 1 is the state BEFORE the action. IMAGE 2 is the state AFTER the action."},
                    {"type": "text", "text": "### START OF IMAGE 1 (BEFORE) ###"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img1_base64}"}},
                    {"type": "text", "text": "### END OF IMAGE 1 ###"},
                    {"type": "text", "text": "### START OF IMAGE 2 (AFTER) ###"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img2_base64}"}},
                    {"type": "text", "text": "### END OF IMAGE 2 ###"},
                    {"type": "text", "text": PROMPT}
                ]
            }
        ]
    }

    response = session.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=payload,
        timeout=60
    )

    response.raise_for_status()

    result = response.json()
    content = result["choices"][0]["message"]["content"]

    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```', '', content).strip()

    return json.loads(content)


# ==========================
# Retry机制（指数退避）
# ==========================

def analyze_with_retry(img1, img2):
    global global_api_errors

    for i in range(RETRY):

        try:
            return analyze_ui_transition(img1, img2)

        except Exception as e:

            sleep_time = RETRY_BASE_SLEEP ** i

            print(f"[Retry] {i + 1}/{RETRY}  sleep={sleep_time}s")

            error_logger.error(str(e))

            if i == RETRY - 1:
                global_api_errors += 1
                return None

            time.sleep(sleep_time)


# ==========================
# CSV清理
# ==========================

def clean_and_load_csv():
    completed_pairs = set()

    headers = ["before", "after", "continuous", "error_type", "reason"]

    valid_error_types = {"none", "accidental_touch", "no_transition"}

    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

        return completed_pairs

    valid_rows = []

    with open(OUTPUT_CSV, "r", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            if not row:
                continue

            error_type = str(row.get("error_type")).strip()

            if error_type not in valid_error_types:
                continue

            completed_pairs.add((row["before"], row["after"]))
            valid_rows.append(row)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(valid_rows)

    return completed_pairs


# ==========================
# CSV写入
# ==========================

def append_csv_safe(row):
    with csv_lock:
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)


# ==========================
# 进度输出
# ==========================

def update_progress():
    global global_completed
    global global_success
    global global_failed

    with progress_lock:
        global_completed += 1

        percent = (global_completed / global_total) * 100

        print(
            f"[PROGRESS] {global_completed}/{global_total} "
            f"({percent:.2f}%) | success={global_success} "
            f"failed={global_failed} api_errors={global_api_errors}"
        )


# ==========================
# 解析 gestures.json
# ==========================

def parse_gestures(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    keys = sorted(data.keys(), key=lambda x: int(x))

    transitions = []

    for i in range(len(keys) - 1):
        before = keys[i]
        after = keys[i + 1]

        transitions.append((before, after, data[before]))

    return transitions


# ==========================
# 单任务
# ==========================

def process_task(task):
    global global_success
    global global_failed

    before_name = task["before_name"]
    after_name = task["after_name"]
    img1 = task["img1"]
    img2 = task["img2"]
    gesture = task["gesture"]

    if gesture == [[]]:
        append_csv_safe([before_name, after_name, True, "none", "no gesture"])

        global_success += 1
        update_progress()
        return

    result = analyze_with_retry(img1, img2)

    if result is None:

        append_csv_safe([before_name, after_name, False, "api_failed", "api error"])
        global_failed += 1

    else:

        append_csv_safe([
            before_name,
            after_name,
            result.get("continuous"),
            result.get("error_type"),
            result.get("reason")
        ])

        global_success += 1

    update_progress()


# ==========================
# 构建任务
# ==========================

def build_tasks(predicted):
    tasks = []

    for app in os.listdir(FILTERED_ROOT):

        app_path = os.path.join(FILTERED_ROOT, app)

        if not os.path.isdir(app_path):
            continue

        for trace in os.listdir(app_path):

            trace_path = os.path.join(app_path, trace)

            gesture_file = os.path.join(trace_path, "gestures.json")

            if not os.path.exists(gesture_file):
                continue

            transitions = parse_gestures(gesture_file)

            for before, after, gesture in transitions:

                before_name = f"{app}_{trace}_{before}.jpg"
                after_name = f"{app}_{trace}_{after}.jpg"

                if (before_name, after_name) in predicted:
                    continue

                img1 = os.path.join(
                    SCREENSHOT_ROOT, app, trace, "screenshots", f"{before}.jpg")

                img2 = os.path.join(
                    SCREENSHOT_ROOT, app, trace, "screenshots", f"{after}.jpg")

                if not os.path.exists(img1) or not os.path.exists(img2):
                    continue

                tasks.append({
                    "before_name": before_name,
                    "after_name": after_name,
                    "img1": img1,
                    "img2": img2,
                    "gesture": gesture
                })

                if MAX_SAMPLES and len(tasks) >= MAX_SAMPLES:
                    return tasks

    return tasks


# ==========================
# 主程序
# ==========================

def main():
    global global_completed
    global global_total

    start_time = time.time()

    print("===================================")
    print("UI TRANSITION AUDITOR")
    print("===================================")

    print("Loading previous CSV...")

    predicted = clean_and_load_csv()

    global_completed = len(predicted)

    print("Completed previously:", global_completed)

    print("Scanning dataset...")

    tasks = build_tasks(predicted)

    global_total = global_completed + len(tasks)

    print("Pending tasks:", len(tasks))
    print("Total target:", global_total)

    if not tasks:
        print("All tasks completed.")
        return

    print("Starting workers:", MAX_WORKERS)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

        futures = [executor.submit(process_task, t) for t in tasks]

        for future in as_completed(futures):

            try:
                future.result()

            except Exception as e:
                error_logger.error(str(e))

    end_time = time.time()

    print("===================================")
    print("FINISHED")
    print("===================================")

    print("Total:", global_total)
    print("Success:", global_success)
    print("Failed:", global_failed)
    print("API errors:", global_api_errors)

    print("Time:", round(end_time - start_time, 2), "seconds")


# ==========================
# 启动
# ==========================

if __name__ == "__main__":
    main()
