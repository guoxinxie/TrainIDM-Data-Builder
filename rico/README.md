## RICO 数据集转换为多模态大语言模型数据处理工具
本工具用于将 RICO Interaction Traces数据集（TFRecord 格式）解析、提取并转换为 **多模态大语言模型（如 Qwen-VL）微调所需的数据格式**。

脚本可提取“操作前截图”和“操作后截图”，并构造问答对，要求模型根据两张图的差异输出导致状态变化的动作（Action JSON）。

### 一、下载RICO的Interaction Traces数据集并解压至filtered_traces层

### 二、下载已经筛选好的gui_transition_result.csv（或者通过同目录下的filter工具微调后筛选）

- 筛除原因：
  - 有大量不是真正意义上的前后帧之间的动作
  - 有误触的情况

### 三、下载rico_Transform.py

该脚本用于处理 **RICO 数据集** (Android UI 交互轨迹)，将原始的屏幕截图和手势坐标数据 (`gestures.json`) 转换为AndroidControl数据集的action space结构化的 `(状态前, 动作, 状态后)` JSON 格式数据集。

#### 处理静态规则（从上往下处理）

- Wait / Open App:
  -  对 ”500”:[[ ]] 的情况处理，说明是没有轨迹操作，是AndroidControl的wait或者是open_app动作。
  -  判断方法：如果在每条轨迹第一个就为”500”:[[]]的处理那就为open_app动作，其他位置为wait操作。
  -  **已剔除**,剔除原因：
    -  之前的模型无法删除无动作的情况，容易出现前面在转圈，后面一个随机屏幕，模型容易强行解释
    -  该部分样本较少，且对IDM的训练无意义。
- Click: 单点触摸。
    - 如果为单个坐标就为Click动作。
    - 根据屏幕原来的尺寸还原为像素坐标。
- Navigate Back: y >= 0.93385 且 0.111 <= x <= 0.333 ,0.933<= y <= 0.999。
- Navigate_Home: y >= 0.93385 且 0.389 <= x <= 0.611 ,0.933 <= y <=0.999。（已剔除）
  - 剔除原因：筛选后navigate_home: 1，且样本没有底部导航栏。
- Scroll: 多点触摸且首尾位移大于屏幕尺寸的 1%（0.01）。
- Long Press: 多点触摸但首尾位移极小（小于屏幕尺寸的 1%）。

#### 核心功能

- 1. **基础动作解析**：将原始归一化坐标转换为带有绝对像素的 `click`（点击）、`scroll`（滑动，包含上下左右方向）和 `long_press`（长按）。
- 2. **精确导航识别**：基于特定的屏幕坐标区域（底部导航栏），精准识别 `navigate_back` (返回) 操作。
- 3. **无效动作清洗**：自动剔除对训练无意义的 `wait` (无操作等待) 和 `open_app` (打开应用前的初始状态) 动作。
- 4. **CSV 状态转换过滤**：结合外部评估的 CSV 文件 (`gui_transition_result.csv`)，通过黑名单机制，自动跳过被标记为 `continuous: FALSE` (非连续/无效转场) 的图片对。

#### 环境依赖

运行此脚本需要安装以下依赖库：

```bash
pip install Pillow
```
#### 数据准备

在运行脚本前，请确保您的文件目录符合以下结构：

- 1. **RICO 轨迹数据目录** (`filtered_traces`):

   ```text
   filtered_traces/
   ├── app_package_name_1/
   │   ├── trace_1/
   │   │   ├── gestures.json
   │   │   └── screenshots/
   │   │       ├── 1.jpg
   │   │       ├── 2.jpg
   │   │       ...
   ├── app_package_name_2/
   ...
   ```

- 2. **已完成筛除的文件** (`gui_transition_result.csv`)

#### 参数配置

```python
# ===================== 配置 =====================
# 1. RICO 原始数据集的根目录
rico_root = "/data/filtered_traces"

# 2. 处理后生成的 JSON 保存路径
output_json = "/data/rico_actions_processed.json"

# 3. 用于过滤连续状态的 CSV 文件路径
csv_path = "/data/gui_transition_result.csv"
```

#### 运行脚本


```bash
python rico_Transform.py
```
**运行过程说明**：
- 1. 脚本会首先读取 CSV 文件并构建需要跳过的“黑名单”集合。
- 2. 接着遍历每一个 App 和 Trace，处理图片对并解析动作。
- 3. 终端会每处理 2000 条有效数据打印一次进度。
- 4. 运行结束后，会在终端打印出各类动作（click, scroll 等）的最终统计数量。

#### 输出数据格式 (JSON)
```json
[
  {
    "trace_id": "aa.apps.dailyreflections_trace_1",
    "image_before": "35.jpg",
    "image_after": "43.jpg",
    "action": {
      "action_type": "click",
      "x": 787,
      "y": 1494
    }
  },
  {
    "trace_id": "aa.apps.dailyreflections_trace_1",
    "image_before": "43.jpg",
    "image_after": "88.jpg",
    "action": {
      "action_type": "click",
      "x": 1041,
      "y": 40
    }
  },
  {
    "trace_id": "aa.apps.dailyreflections_trace_1",
    "image_before": "88.jpg",
    "image_after": "93.jpg",
    "action": {
      "action_type": "click",
      "x": 770,
      "y": 256
    }
  },
...
]
```





