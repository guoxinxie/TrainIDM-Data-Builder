# Android UI 多模态微调数据处理工具

本工具用于将 Android_Control控制数据集（TFRecord 格式）解析、提取并转换为 **多模态大语言模型（如 Qwen-VL）微调所需的数据格式**。

脚本可提取“操作前截图”和“操作后截图”，并构造问答对，要求模型根据两张图的差异输出导致状态变化的动作（Action JSON）。

##  核心特性

- **自动提取图片**：从 TFRecord 的二进制数据中提取截图，并按任务 ID (`episode_id`) 分类保存为本地 PNG 文件。
- **断点跳过**：若图片目录已存在，则自动跳过图片保存步骤，加快调试和重复运行的效率。
- **Qwen-VL 格式兼容**：默认生成支持多图输入的 `Human-GPT` 格式微调 JSON。
- **动作统计**：在终端自动输出 `click`, `scroll`, `input_text` 等动作的统计分布。

##  环境依赖

请确保您的 Python 环境中安装了以下依赖：

```bash
pip install tensorflow pillow
```

##  参数配置

在运行脚本前，您可以根据需要修改脚本开头的配置参数：
code
```Python
# ================= 配置 =================
tfrecord_dir = "data/android_control"              # 存放原始 TFRecord 数据集的目录
output_json = "data/android_control_qwenvl.json"   # 生成的微调 JSON 文件名称
save_image_dir = "data/images"                     # 提取出的截图保存的本地物理路径
image_prefix = "data/images"                       # 写入 JSON 中图片路径的前缀（需与训练时挂载路径一致）

# 提问 Prompt（可根据您的训练模型需求修改）
human_prompt = (
    "<image>\n"
    "<image>\n"
    "Observe the two screenshots before and after. "
    "Output the action JSON that caused this state change."
)
# ========================================
```

##  使用方法
将您的 android_control的TFRecord 文件（支持 .gz 压缩格式）放入您修改的目录中。
运行数据处理脚本：

```bash
python android_control_index.py
```
运行结束后，终端将输出动作的统计分布情况
例如
```bash
==============================
Action Statistics
==============================
click          : 15420
long_press     : 320
scroll         : 4210
open_app       : 50
...
------------------------------
Total Actions: 20000
```
##  JSON 数据格式

生成的 android_control_qwenvl.json 内容结构完全符合 Qwen-VL 等多模态模型的官方微调格式：
```json
[
  {
    "image": [
      "images/1001/screenshots/0.png",
      "images/1001/screenshots/1.png"
    ],
    "conversations": [
      {
        "from": "human",
        "value": "<image>\n<image>\nObserve the two screenshots before and after. Output the action JSON that caused this state change."
      },
      {
        "from": "gpt",
        "value": "{\"action_type\": \"click\", \"y\": 853, \"x\": 412}"
      }
    ]
  }
]
```

##  示例最后的目录结构
```bash
├── android_control/             # 原始 TFRecord 目录
├── images/                      # 提取的图片目录
│   ├── 1001/
│   │   └── screenshots/
│   │       ├── 0.png
│   │       ├── 1.png
│   │       └── ...
│   └── 1002/
├── process_data.py              # 本脚本
└── android_control_qwenvl.json  # 最终生成的训练数据
```
