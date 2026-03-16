import os
import json
import tensorflow as tf
from PIL import Image
import io

# ================= 配置 =================

tfrecord_dir = "data/android_control"

# 输出json
output_json = "data/android_control_qwenvl.json"

# 图片保存目录
save_image_dir = "data/images"

# 训练时的图片路径前缀
image_prefix = "data/images"

# human prompt
human_prompt = (
    "<image>\n"
    "<image>\n"
    "Observe the two screenshots before and after. "
    "Output the action JSON that caused this state change."
)

# ========================================

os.makedirs(save_image_dir, exist_ok=True)

dataset = []

# ===============================
# 动作统计
# ===============================

action_stats = {
    "click": 0,
    "long_press": 0,
    "scroll": 0,
    "open_app": 0,
    "input_text": 0,
    "navigate_home": 0,
    "navigate_back": 0,
    "wait": 0,
    "unknown": 0
}

# -------- 查找 TFRecord 文件 --------

tfrecord_files = []

for root, dirs, files in os.walk(tfrecord_dir):
    for f in files:

        if f.endswith(".json") or f.endswith(".csv"):
            continue

        if "android_control-" in f:
            tfrecord_files.append(os.path.join(root, f))

print("发现 TFRecord 文件数量:", len(tfrecord_files))

# -------- 解析 TFRecord --------

for tfrecord_path in tfrecord_files:

    print("Processing:", tfrecord_path)

    dataset_tf = tf.data.TFRecordDataset([tfrecord_path], compression_type="GZIP")

    for raw_record in dataset_tf:

        try:

            example = tf.train.Example.FromString(raw_record.numpy())
            features = example.features.feature

            # -------- episode_id --------

            episode_id = None

            if "episode_id" in features:

                feat = features["episode_id"]

                if feat.int64_list.value:
                    episode_id = int(feat.int64_list.value[0])

                elif feat.bytes_list.value:
                    episode_id = int(feat.bytes_list.value[0].decode())

            if episode_id is None:
                continue

            ep_dir = os.path.join(save_image_dir, str(episode_id), "screenshots")

            # -------- screenshots --------

            screenshots = []

            if "screenshots" in features:

                if not os.path.exists(ep_dir):
                    os.makedirs(ep_dir, exist_ok=True)

                    for idx, img_bytes in enumerate(features["screenshots"].bytes_list.value):

                        img = Image.open(io.BytesIO(img_bytes))

                        img_path = os.path.join(ep_dir, f"{idx}.png")
                        img.save(img_path)

                        screenshots.append(f"{idx}.png")

                else:
                    screenshots = sorted(os.listdir(ep_dir), key=lambda x: int(x.split(".")[0]))

            # -------- actions --------

            actions = []

            if "actions" in features:

                for a in features["actions"].bytes_list.value:

                    try:
                        action = json.loads(a.decode("utf-8"))
                    except:
                        action = a.decode("utf-8")

                    actions.append(action)

            # -------- 构造样本 --------

            num_steps = min(len(actions), len(screenshots) - 1)

            for i in range(num_steps):

                action = actions[i]

                # ===============================
                # 动作统计逻辑
                # ===============================

                if isinstance(action, dict):

                    action_type = action.get("action_type")

                    if action_type in action_stats:
                        action_stats[action_type] += 1
                    else:
                        action_stats["unknown"] += 1

                else:
                    action_stats["unknown"] += 1

                # ===============================

                img1 = f"{image_prefix}/{episode_id}/screenshots/{screenshots[i]}"
                img2 = f"{image_prefix}/{episode_id}/screenshots/{screenshots[i+1]}"

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

# -------- 保存 JSON --------

with open(output_json, "w", encoding="utf-8") as f:
    json.dump(dataset, f, indent=2, ensure_ascii=False)

# -------- 输出统计 --------

print("\n==============================")
print("Action Statistics")
print("==============================")

total_actions = sum(action_stats.values())

for k, v in action_stats.items():
    print(f"{k:15s}: {v}")

print("------------------------------")
print("Total Actions:", total_actions)

print("\n完成")
print("样本数量:", len(dataset))
print("输出:", output_json)
