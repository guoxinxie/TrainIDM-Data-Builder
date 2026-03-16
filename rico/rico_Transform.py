import os
import json
import csv
from PIL import Image

# ===================== 配置 =====================

rico_root = "/data/filtered_traces"

output_json = "/data/rico_actions_processed.json"

csv_path = "/data/gui_transition_result.csv"


# ===================== 读取CSV过滤规则 =====================

skip_pairs = set()

print("读取 UI transition CSV...")

with open(csv_path, "r", encoding="utf-8") as f:

    reader = csv.DictReader(f)

    for row in reader:

        if row["continuous"].strip().upper() == "FALSE":

            before = row["before"]
            after = row["after"]

            skip_pairs.add((before, after))

print("需要跳过的 transition 数量:", len(skip_pairs))


# ===================== 动作解析 =====================

def parse_action(coords, img_path):

    if not coords or len(coords) == 0:
        return [{"action_type": "wait"}]

    w, h = Image.open(img_path).size

    actions = []

    # ================= click =================

    if len(coords) == 1:

        x_norm = coords[0][0]
        y_norm = coords[0][1]

        x = int(x_norm * w)
        y = int(y_norm * h)

        # 默认先添加基础的click动作
        actions.append({
            "action_type": "click",
            "x": x,
            "y": y
        })

        # ================= 精确导航识别 =================
        # 移除了 navigate_home 的判断逻辑
        if y_norm >= 0.93385:
            # navigate_back
            if 0.111 <= x_norm <= 0.333 and 0.933 <= y_norm <= 0.999:
                actions.append({"action_type": "navigate_back"})

        return actions

    # ================= scroll / long_press =================

    if len(coords) > 1:

        start = coords[0]
        end = coords[-1]

        dx = abs(end[0] - start[0])
        dy = abs(end[1] - start[1])

        # scroll
        if max(dx, dy) >= 0.01:

            if abs(dx) > abs(dy):
                direction = "right" if end[0] > start[0] else "left"
            else:
                direction = "down" if end[1] > start[1] else "up"

            return [{
                "action_type": "scroll",
                "direction": direction
            }]

        # long_press
        else:

            x = int(start[0] * w)
            y = int(start[1] * h)

            return [{
                "action_type": "long_press",
                "x": x,
                "y": y
            }]

    return [{"action_type": "wait"}]


# ===================== 构建数据 =====================

dataset = []

action_stats = {
    "click": 0,
    "scroll": 0,
    "long_press": 0,
    "navigate_back": 0
    # 移除了 "navigate_home": 0
}

apps = os.listdir(rico_root)

for app in apps:

    app_dir = os.path.join(rico_root, app)

    if not os.path.isdir(app_dir):
        continue

    print("APP:", app)

    for trace in os.listdir(app_dir):

        if not trace.startswith("trace"):
            continue

        trace_dir = os.path.join(app_dir, trace)

        screenshots_dir = os.path.join(trace_dir, "screenshots")
        gestures_path = os.path.join(trace_dir, "gestures.json")

        if not os.path.exists(gestures_path):
            continue

        if not os.path.exists(screenshots_dir):
            continue

        trace_id = f"{app}_{trace}"

        screenshots = sorted(
            [f for f in os.listdir(screenshots_dir)
             if f.endswith(".jpg") and f.split(".")[0].isdigit()],
            key=lambda x: int(x.split(".")[0])
        )

        if len(screenshots) < 2:
            continue

        with open(gestures_path, "r") as f:
            gestures = json.load(f)

        for i in range(len(screenshots) - 1):

            img1 = screenshots[i]
            img2 = screenshots[i + 1]

            idx = img1.split(".")[0]

            coords = gestures.get(idx, [])

            img_path = os.path.join(screenshots_dir, img1)

            # ================= CSV过滤 =================

            before_name = f"{trace_id}_{img1}"
            after_name = f"{trace_id}_{img2}"

            if (before_name, after_name) in skip_pairs:
                continue

            # ================= 动作解析 =================

            actions = parse_action(coords, img_path)

            # ================= open_app逻辑 =================

            if i == 0 and len(actions) == 1 and actions[0]["action_type"] == "wait":
                actions = [{
                    "action_type": "open_app"
                }]

            # ================= 保存动作 =================

            for action in actions:

                action_type = action["action_type"]

                # 跳过 wait 和 open_app
                if action_type in ["wait", "open_app"]:
                    continue

                dataset.append({
                    "trace_id": trace_id,
                    "image_before": img1,
                    "image_after": img2,
                    "action": action
                })

                if action_type in action_stats:
                    action_stats[action_type] += 1

            if len(dataset) % 2000 == 0 and len(dataset) > 0:
                print("已生成:", len(dataset))


# ===================== 动作统计 =====================

print("\n========== 动作统计 ==========")

total = sum(action_stats.values())

for k, v in action_stats.items():
    print(f"{k}: {v}")

print("----------------------------")
print("Total:", total)


# ===================== 保存JSON =====================

with open(output_json, "w", encoding="utf-8") as f:
    json.dump(dataset, f, indent=2, ensure_ascii=False)

print("\n输出文件:", output_json)