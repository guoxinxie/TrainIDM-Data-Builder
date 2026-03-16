import os
import json

# ================= 配置 =================

rico_action_json = "/data/rico_actions_processed.json"

trace_root = "/data/filtered_traces"

output_json = "/data/rico_qwenvl.json"

image_prefix = "/data/filtered_traces"

human_prompt = (
    "<image>\n"
    "<image>\n"
    "Observe the two screenshots before and after. "
    "Output the action JSON that caused this state change."
)

# ========================================

dataset = []

action_stats = {}

print("扫描 screenshots...")

image_map = {}

# 建立 image index
for root, dirs, files in os.walk(trace_root):

    if os.path.basename(root) == "screenshots":

        for f in files:

            if f.endswith(".jpg") or f.endswith(".png"):

                key = os.path.join(root, f)
                image_map[key] = key

print("找到截图:", len(image_map))

# -------------------------
# 读取 actions
# -------------------------

with open(rico_action_json, "r", encoding="utf-8") as f:
    actions_data = json.load(f)

print("动作数量:", len(actions_data))

# -------------------------
# 查找图片函数
# -------------------------

def find_image(filename):

    for path in image_map:

        if path.endswith("/" + filename) or path.endswith("\\" + filename):
            return path

    return None


# -------------------------
# 构造样本
# -------------------------

for item in actions_data:

    try:

        img_before = item["image_before"]
        img_after = item["image_after"]

        action = item["action"]
        action_type = action.get("action_type", "unknown")

        action_stats[action_type] = action_stats.get(action_type, 0) + 1

        path1 = find_image(img_before)
        path2 = find_image(img_after)

        if path1 is None or path2 is None:
            continue

        # 转为训练路径
        p1 = path1.replace("\\", "/").split("filtered_traces/")[1]
        p2 = path2.replace("\\", "/").split("filtered_traces/")[1]

        img1 = f"{image_prefix}/{p1}"
        img2 = f"{image_prefix}/{p2}"

        sample = {
            "image": [
                img1,
                img2
            ],
            "conversations": [
                {
                    "from": "human",
                    "value": human_prompt
                },
                {
                    "from": "gpt",
                    "value": json.dumps(action, ensure_ascii=False)
                }
            ]
        }

        dataset.append(sample)

    except Exception as e:
        print("Error:", e)

# -------------------------
# 保存
# -------------------------

with open(output_json, "w", encoding="utf-8") as f:
    json.dump(dataset, f, indent=2, ensure_ascii=False)

# -------------------------
# 统计
# -------------------------

print("\n===== Action Stats =====")

for k, v in action_stats.items():
    print(k, v)

print("\n样本数量:", len(dataset))
print("输出:", output_json)
