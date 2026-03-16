## 筛选RIOC数据集的脚本工具

本工具用于对RICO的Interaction Traces数据集，进行**还原轨迹**，并**筛选出可以用于训练IDM**的样本。

### 一、下载RICO的Interaction Traces数据集并解压至filtered_traces层

### 二、下载Restore_trace.py
本脚本用于处理 RICO 数据集（或类似结构的 UI 交互数据集）。其核心功能是读取每个交互序列（trace）中的截图，并根据 `gestures.json` 文件中记录的手势坐标，在对应的截图上**可视化地绘制出用户操作（点击或滑动）**。

最终，所有处理过的图片将被转换成 `.jpg` 格式并保存到指定的输出目录，同时保持原始的数据集目录结构。这对于数据分析、模型训练样本的标注或创建演示材料非常有用。

####  核心特性

- **手势可视化**:
  - **点击 (Click)**: 在单点触摸位置绘制一个醒目的蓝色圆点。
  - **滑动 (Swipe)**: 绘制一条从起点到终点的蓝色轨迹线，其中起点为绿色，终点为红色。
- **保持目录结构**: 自动在输出目录中创建与原始数据集完全相同的子目录结构，方便管理。
- **格式转换与压缩**: 将所有原始图片（如 `.png`）统一转换为高质量的 `.jpg` 格式，有助于减小存储体积。
- **元数据同步**: 自动将 `gestures.json` 文件复制到新的 trace 目录中，确保数据完整性。

####  环境依赖

请确保您的 Python 环境中安装了 Pillow 库：

```bash
pip install Pillow
```
####  参数配置
在运行脚本前，请根据您的实际情况修改脚本开头的配置参数：
```python
# =============================
# 配置
# =============================

# 原始 RICO 数据集根目录
rico_root = "/data/filtered_traces"

# 处理后图片的输出根目录
output_root = "/data/screenshots_jpg"

# 绘制手势点的半径大小（像素），调整此值可改变绘制点的大小
POINT_RADIUS = 12
```
#### 使用方法
修改脚本配置并运行
```bash
python Restore_trace.py
```
#### 输入与输出说明
*输入*：
```text
data/filtered_traces/
└── trace_1/
    ├── gestures.json
    └── screenshots/
        ├── 1.png
        ├── 2.png
        └── ...
└── trace_2/
    ├── gestures.json
    └── screenshots/
        ├── 1.png
        └── ...
```
*输出*:
```text
data/screenshots_jpg/
└── trace_1/
    ├── gestures.json
    └── screenshots/
        ├── 1.jpg   
        ├── 2.jpg   
        └── ...
└── trace_2/
    ├── gestures.json
    └── screenshots/
        ├── 1.jpg   
        └── ...
```
- **`gestures.json`**: 一个 JSON 文件，其键是截图的编号（如 "1", "2"），值是在该截图上执行的手势坐标。脚本使用此文件来确定连续的截图对（例如，1 -> 2, 2 -> 3）。
#### 效果示例
<p align="center">
<img src="image/35.jpg" width="300">
<img src="image/image1.jpg" width="300">
</p>
<p align="center">
<img src="image/700.jpg" width="300">
<img src="image/image.jpg" width="300">
</p>

### 三、下载filter_by_Gemini.py
本脚本是一个自动化筛选工具， 用于RICO 数据集中的 UI 转换逻辑一致性进行验证。它通过分析“操作前”与“操作后”的成对截图来判断“操作前”图片中显示的用户手势，是否是导致“操作后”图片状态变化的直接且唯一的原因。脚本会对此类转换进行分类，并将结果保存到结构化的 CSV 文件中，以便后续进行数据分析和清洗。

####  核心特性

- **多线程并行处理**: 利用 `ThreadPoolExecutor` 并发执行 API 请求，**大幅提升处理速度**，有效缩短在大型数据集上的总运行时间。
- **断点续传与数据清理**: 脚本启动时会自动加载并**清理**已有的 CSV 结果，移除无效或未完成的行。这使得任务可以随时中断和恢复，无需担心数据损坏或重复工作。
- **指数退避重试机制**: 内置了智能的 API 请求重试逻辑。当遇到网络波动或 API 临时错误时，会以**指数增加的间隔时间**进行重试，极大地提高了任务的成功率和稳定性。
- **企业级日志系统**:
  - `run.log`: 记录程序运行的关键信息和进度。
  - `error.log`: **独立记录**所有发生的错误，包括 API 异常和代码执行错误，便于快速定位和解决问题。
- **HTTP 连接复用**: 通过 `requests.Session` 保持长连接，减少了 TCP 握手次数，进一步优化了高并发请求下的网络性能。
- **线程安全**: 对 CSV 文件写入和进度更新操作使用了线程锁 (`threading.Lock`)，确保在多线程环境下数据的一致性和准确性。


#### 环境准备与设置

1.  **安装依赖库**: 使用 pip 安装所需的 Python 包。
    ```bash
    pip install requests pillow
    ```
2.  **获取 API 密钥**: 本脚本需要使用 [OpenRouter.ai](https://openrouter.ai/) 提供的 API 密钥。您可以将此密钥设置为环境变量或者设置到参数配置中。

#### 参数配置

在运行脚本前，请根据您的实际需求，修改脚本顶部的配置参数：

```python
# ==========================
# 配置
# ==========================

# 数据集根目录
FILTERED_ROOT = "/data/screenshots_jpg"
SCREENSHOT_ROOT = "/data/screenshots_jpg"

# 结果输出的 CSV 文件路径
OUTPUT_CSV = "/data/gui_transition_result.csv"

# 最多处理的样本数量（设置为 None 表示处理全部）
MAX_SAMPLES = None
# 并发执行的线程数量（可并发处理节省时间，根据您的网络和机器性能调整）
MAX_WORKERS = 10

# API 请求重试次数
RETRY = 10
# 重试的基础等待时间（秒），后续等待时间会指数增长
RETRY_BASE_SLEEP = 2
# 设置API_KEY
API_KEY = os.environ.get("OPENROUTER_API_KEY",
                         "YOUR_API_KEY")

# 通过 OpenRouter 使用的 VLM 模型
MODEL = "google/gemini-3.1-flash-lite-preview"

# 定义核心分析逻辑的提示词 (可以根据需求微调)
PROMPT = """..."""
```

#### 使用方法
修改脚本配置并运行
```bash
python filter_by_Gemini.py
```
脚本将开始处理数据，并在控制台打印进度。如果您中途停止脚本，下次运行时它会自动从上次中断的地方继续。

#### 数据结构说明

##### 输入数据结构

脚本期望的输入数据采用以下嵌套目录结构：

```text
<SCREENSHOT_ROOT>/
└── <app_name>/
    └── <trace_id>/
        ├── gestures.json
        └── screenshots/
            ├── 1.jpg
            ├── 2.jpg
            └── ...
```

- **`gestures.json`**: 一个 JSON 文件，其键是截图的编号（如 "1", "2"），值是在该截图上执行的手势坐标。脚本使用此文件来确定连续的截图对（例如，1 -> 2, 2 -> 3）。

##### 输出 CSV 结构

脚本将生成一个 CSV 文件（路径由 `OUTPUT_CSV` 指定），包含以下列：
```text
| 列名         | 描述                                                       |
|--------------|------------------------------------------------------------|
| `before`     | 操作前截图的文件名。                                       |
| `after`      | 操作后截图的文件名。                                       |
| `continuous` | 如果转换逻辑上是连续的，则为 `True`，否则为 `False`。        |
| `error_type` | 错误类型分类：`none`, `accidental_touch`, `api_failed` 等。 |
| `reason`     | AI 模型为其分类提供的文字解释。                            |
```

#### Prompt 原理
本脚本的分析能力核心来源于精心设计的 `PROMPT` 变量。它指示模型扮演一个“严格的UI轨迹审计员”，并遵循一套严谨的、分步的评估流程：
-**步骤一**识别动作与目标（仅分析Image 1）:
  -1.动作类型识别，检查图像中是否存在手势标记，蓝色圆点 → 点按(Tap)，红点→蓝线→绿点 → 滑动(Swipe)。
  -2.目标元素定位，准确定位手势标记覆盖的UI元素，比如"设置按钮"、"用户名输入框"、"列表空白区域"。
-**步骤二**观察状态变化（对比Image 1与Image 2）:
  -1.识别核心差异，对比两张图像，提取最显著的视觉变化，比如"页面跳转至个人资料页"、"列表内容向上滚动"、"弹出确认删除对话框"
-**步骤三**建立因果关联（逻辑推理）:
  -1.逻辑一致性检验，将步骤一的"动作+目标"与步骤二的"状态变化"进行匹配，核心判断标准："在[目标]上执行[动作]是否应导致[状态变化]"
  -2.逻辑判断示例，合理：点按"登录"按钮 → 进入"主页"，合理：在列表上"向上滑动" → 列表内容滚动，合理："加载中..."界面(系统驱动) → "加载完成"界面，矛盾：点按"服务"标签 → 进入"收件箱"页面，矛盾：点按"空白区域" → 页面发生滚动
-**步骤四**生成最终结论（输出JSON）:
  -1. 分类规则，逻辑合理时（有效轨迹）{"continuous": true, "error_type": "none"}，逻辑矛盾时（无效/错误轨迹）：{"continuous": false, "error_type": "accidental_touch"}
  -2. 解释撰写要求在reason字段中清晰叙述动作、结果及二者逻辑关系需包含步骤一至步骤三的完整分析过程明确指出逻辑合理性或矛盾点。


#### 成功典型案例
模型输出：
<p align="center">
<img src="image/370.jpg" width="300">
<img src="image/488.jpg" width="300">
</p>


```text
false
1.Gesture was a Tap on the 'ONE-WAY' tab. 
2.mage 2 shows the 'ONE-WAY' tab selected, but the origin city has changed from 'Vancouver' to 'Kuala Lumpur'. 
3.Logic: Tapping the 'ONE-WAY' tab should only toggle the trip type; it cannot logically change the departure city field, which requires a separate interaction.
这个例子说明模型对识别动作成功，
观察屏幕状态成功识别两张屏幕元素成功，
逻辑推理成功。
```


