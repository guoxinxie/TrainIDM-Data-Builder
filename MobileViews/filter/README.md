# MobileViews GUI Transition Data Filter (mobileviews数据集的IDM 数据清洗工具)

本脚本是一个基于**视觉大语言模型 (Vision Large Language Model, VLM)** 的移动端 GUI 交互数据自动化清洗工具。
其主要用于评估和筛选出mobileviews中高质量的 `(Before Screen, After Screen) -> Action` 数据对，以为训练**逆动力学模型 (Inverse Dynamics Model, IDM)** 准备高质量的数据集。

---

## 下载filter_trace.py和mobileviews数据集并解压

---

##  数据集目录结构要求

程序会遍历配置的 `ROOT_DIR` 目录。您的原始数据集需遵循以下结构（通常为 DroidBot/Appium 抓取工具的输出格式）：

```text
/data/mv_trace_en/           <-- ROOT_DIR (根目录)
├── AppName_1/               <-- 具体的 App 文件夹
│   ├── utg.js               <-- 交互图谱数据（包含 states 引用及 edges 动作关联）
│   └── states/              <-- 屏幕截图存放目录
│       ├── screen_001.jpg   <-- 具体的截图文件
│       ├── screen_002.jpg
│       └── ...
├── AppName_2/
│   ├── utg.js
│   └── states/
│       ├── screen_A.jpg
│       └── ...
```

*注1：代码会自动解析 `utg.js` 文件，提取状态节点映射，并寻找所有触发状态转移的 Action 及对应的两张图片。*

*注2：使用utg.js原因是因为action.csv有图片自己到自己的动作浪费算力。*

---

##  核心功能

-  **智能视觉分析**：结合前/后两张屏幕截图和动作指令，利用视觉大模型自动判断交互动作的有效性、因果关系及可学习性。
-  **高并发处理**：基于多线程 (`ThreadPoolExecutor`) 实现，大幅提升海量数据的处理速度。
-  **断点续传支持**：自动读取已生成的 CSV 文件，跳过已处理的数据，随时中断和恢复任务而不会丢失进度。
-  **高可用与容错**：内置 API 请求指数退避（Exponential Backoff）重试机制，从容应对网络抖动和 API 限流。
-  **全量 API 兼容**：支持任何兼容 OpenAI 接口格式的模型服务，包括但不限于 OpenRouter、本地部署的 vLLM。
-  **严格的结果结构化**：通过精心设计的 Prompt 强制模型输出标准 JSON 格式，并输出详细的评估理由和违规规则编号。

---

##  环境依赖

确保您的系统中已安装 Python。

安装所需依赖包：
```bash
pip install requests tqdm
```

---


##  配置说明

在运行脚本前，请使用文本编辑器打开 Python 脚本，并修改开头的 `CONFIG` 字典配置：

  ### ================= 路径配置区 =================
    "ROOT_DIR": "/data/mv_trace_en",  - 输入端：原始数据集的根目录。程序会遍历该目录下的各个 APP 文件夹读取 utg.js 和截图
    "OUTPUT_CSV": "/data/filter_mv_trace.csv",  - 输出端：模型评估结果的保存路径。支持断点续传，已存在的数据会自动跳过
    "LOG_FILE": "/data/filter_mv_trace.log",  - 日志端：运行日志保存路径，用于排查报错（如 API 异常、图片读取失败等）

  ### ================= 大模型 API 配置区 =================
    
    - 支持任何兼容 OpenAI 接口格式的服务（如 OpenRouter、本地部署的 vLLM、Ollama 等）
    "API_KEY": "YOUR_API_KEY",  - 你的 API 密钥。如果使用的是本地部署的 vLLM 等无鉴权服务，保持为空字符串即可
    "API_URL": "https://openrouter.ai/api/v1/chat/completions",
    - API 请求地址。若使用本地 vLLM，通常改为 "http://localhost:8000/v1/chat/completions"
    "MODEL": "qwen/qwen3.5-397b-a17b",  - 调用的具体视觉模型名称。必须与提供商（或本地部署）的模型列表名称严格一致

  ### ================= 性能与网络配置区 =================
    "MAX_WORKERS": 10,  - 多线程并发数。
    "REQUEST_TIMEOUT": 120,
    - 注意：视觉大模型（VLM）处理两张高分辨率图片速度较慢，建议保持 60 秒或以上。
    "MAX_RETRIES": 3,  - 单个任务失败（如网络抖动、API 暂时限流）时的最大重试次数。配合代码里的指数退避算法（等待 1, 2, 4 秒后重试）提升稳定性。
    - PROMPT
    "PROMPT": 
    """
    
    """

---

##  运行指南

配置完成后，直接运行 Python 脚本：

```bash
python filter_trace.py
```

### 运行监控
程序运行时，终端会显示 `tqdm` 进度条，实时展示当前处理进度、预估剩余时间，以及最新一条任务的处理结果状态（`Valid`, `Invalid`, `Error`）：

```text
Evaluating New Transitions:  35%|███▌      | 350/1000 [02:15<04:30,  2.41task/s,  Valid]
```

运行结束后，终端会打印本次运行的统计数据（总数、有效比例、无效比例及错误率）。

---


##  输出文件格式 (CSV)

结果将追加写入到您配置的 `OUTPUT_CSV` 文件中，包含以下字段：

| 字段名 | 说明 |
| :--- | :--- |
| `app_name` | 应用程序名称（文件夹名） |
| `from_screen_filename` | 动作发生前的屏幕截图文件名 |
| `to_screen_filename` | 动作发生后的屏幕截图文件名 |
| `action` | 执行的动作指令（如 `touch: View[id=btn_login]`） |
| `valid` | **最终判定**：`TRUE` 表示样本合格，`FALSE` 表示不合格 |
| `action_valid` | 动作有效性（是否为单一动作且目标可见） |
| `causal_correct` | 因果正确性（前后屏幕的变化是否由该动作引起） |
| `idm_learnable` | IDM 可学习性（UI 变化是否有意义、渲染是否完整） |
| `violations` | 触发的违规规则 ID 列表（合格样本为空 `[]`） |
| `reason` | 模型给出的判定理由（1-3句简述） |

---
##  输出结果示例

程序运行后，会向 `OUTPUT_CSV`（如 `/data/filter_mv_trace.csv`）中追加数据。以下是生成的 CSV 文件内容的直观展示：

### 示例 1：合格的高质量数据 (Valid)

| 字段名 | 值示例 | 说明解析 |
| :--- | :--- | :--- |
| `app_name` | `com.youtube.android` | App 包名或文件夹名 |
| `from_screen` | `state_01.jpg` | 动作发生前的界面 |
| `to_screen` | `state_02.jpg` | 动作发生后的界面 |
| `action` | `touch: View[id=search_icon]` | 点击了搜索图标 |
| `valid` | **`TRUE`** | **整体判定为合格** |
| `action_valid` | `TRUE` | 动作单一且目标明确可见 |
| `causal_correct` | `TRUE` | 点击搜索后成功跳转，因果明确 |
| `idm_learnable` | `TRUE` | 搜索页加载完整，特征可学习 |
| `violations` | `[]` | 未触发任何违规规则 |
| `reason` | `The action targets a visible search icon, leading directly to a fully rendered search page.` | 理由：动作指向可见搜索图标，直接导致完全渲染的搜索页面。 |

### 示例 2：被清洗掉的无效数据 (Invalid)

| 字段名 | 值示例 | 说明解析 |
| :--- | :--- | :--- |
| `app_name` | `com.twitter.android` | App 包名或文件夹名 |
| `from_screen` | `state_15.jpg` | 动作发生前的界面 |
| `to_screen` | `state_16.jpg` | 动作发生后的界面 |
| `action` | `touch: View[bounds=[0,0][10,10]]` | 点击了左上角空白无意义区域 |
| `valid` | **`FALSE`** | **整体判定为不合格** |
| `action_valid` | `FALSE` | (触发Rule 1) 点击了空白背景 |
| `causal_correct` | `FALSE` | (触发Rule 4) 界面毫无变化 |
| `idm_learnable` | `FALSE` | (触发Rule 6) 无意义的变化 |
| `violations` | **`[1, 4, 6]`** | **命中了第1, 4, 6条淘汰规则** |
| `reason` | `The action targets a blank background area and results in no meaningful UI changes.` | 理由：动作针对空白背景区域，且未导致有意义的UI变化。 |

---




##  详细评估规则与执行流程

本工具的核心在于利用视觉大模型（VLM）模拟一位严谨、遵循既定流程的质量检验专家。为了保证评估结果的高度一致性和准确性，模型被强制要求遵循一个**不可更改的四步评估程序**。

---

### **第一步：初步评估三大准入标准**

在这一阶段，模型会对交互样本进行初步的“正面评估”，判断其是否具备成为一个合格样本的基本素质。这并非最终结论，而是资格预审。

1.  **动作有效性 (`action_valid`)**
    *   **核心问题**：这个动作本身是合法的吗？
    *   **评估内容**：动作指令是否为单一、原子化的操作？其目标（坐标或UI元素）是否在 `Screen 1` 中清晰可见且理论上可交互？

2.  **因果正确性 (`causal_correct`)**
    *   **核心问题**：这个动作是否导致了合乎逻辑的界面变化？
    *   **评估内容**：`Screen 1` 到 `Screen 2` 是否存在由该动作直接引起的、符合移动端交互常识的视觉变化？

3.  **模型可学习性 (`idm_learnable`)**
    *   **核心问题**：这个交互结果对AI模型来说有学习价值吗？
    *   **评估内容**：UI的变化是否足够清晰、有意义？`Screen 2` 是否是一个渲染完整、稳定的最终状态，而非加载动画或过渡帧？

> **注意**：即使在这一步所有标准都初步判断为 `TRUE`，也**不代表样本最终合格**。最终决定权在第二步的规则核查。

---

### **第二步：交叉核查八大淘汰规则（强制性）**

这是整个流程中最关键的**“负面清单”审查**环节。模型被强制要求**独立地、无遗漏地**检查所有8条规则，**即使样本在第一步看起来完全合格也不能跳过此步骤**。

*   **[Rule 1] 动作异常 (Action Error)**
    *   **淘汰情形**：动作指令为空、包含多步操作，或指向了 `Screen 1` 中不存在的元素。最常见的是动作区域完全落在没有任何可交互元素的空白背景上。

*   **[Rule 2] 桌面干扰 (No Home Screen Transitions)**
    *   **淘汰情形**：交互的起点或终点是手机操作系统桌面（Home Screen/Launcher），例如App的启动或退出过程。这不属于App内部的交互逻辑。

*   **[Rule 3] 语义错乱 (Semantic Mismatch)**
    *   **淘汰情形**：交互结果严重违反UI设计常识。例如，点击一个“设置”图标却打开了摄像头，或者点击“返回”按钮却进入了更深一级的菜单。

*   **[Rule 4] 动作失效 (Action Failure)**
    *   **淘汰情形**：执行动作后，UI界面没有任何可辨识的变化。或者，UI的变化与动作类型完全不符（如`tap`操作导致了`scroll`效果）。

*   **[Rule 5] 系统干扰 (System Interference)**
    *   **淘汰情形**：`Screen 2` 中出现了非App本身的系统级UI元素，如系统警告、或来自其他App的浮动通知。
        **例外情况**： 操作系统级的 UI，例如权限对话框，如果是用户操作的直接且合理的结果，则被视为**有效**。
*   **[Rule 6] 无意义变化 (No Meaningful Change)**
    *   **淘汰情形**：前后两张图几乎完全相同，仅有时间、电量、输入框光标闪烁等微不足道的变化。也包括密码输入框中内容从明文变为`***`的情况，因为模型无法从视觉上学习到具体输入。

*   **[Rule 7] 渲染未完成 (Incomplete Rendering)**
    *   **淘汰情形**：`Screen 2` 明显处于加载状态，显示的是加载动画（菊花图）、骨架屏（Skeleton Screen）、白屏或内容尚未完全载入。

*   **[Rule 8] 无效滑动 (Invalid Scroll)**
    *   **淘汰情形**：执行了`scroll`动作，但页面内容没有产生清晰、连贯的位移，或者滑动幅度极小几乎无法察觉。

---

### **第三步：基于规则进行最终判定**

这一步的逻辑非常简单且严格，直接根据第二步的核查结果做出最终裁决：

*   如果**没有任何一条**淘汰规则被触发 -> 最终结果 `valid` = **`TRUE`**。
*   如果**任意一条或多条**淘汰规则被触发 -> 最终结果 `valid` = **`FALSE`**。

---

### **第四步：确保评估结果的内部一致性**

这是最后的“自检”步骤，确保输出的JSON数据是逻辑自洽的。模型必须保证第一步评估的三个标准字段与第二步触发的淘汰规则严格对应。

*   **一致性要求：**
    *   如果触发了 **[Rule 1]** -> `action_valid` 必须为 `FALSE`。
    *   如果触发了 **[Rule 3], [Rule 4], 或 [Rule 5]** -> `causal_correct` 必须为 `FALSE`。
    *   如果触发了 **[Rule 6], [Rule 7], 或 [Rule 8]** -> `idm_learnable` 必须为 `FALSE`。
    *   如果没有触发任何规则，则所有三个标准都必须为 `TRUE`。

这个步骤保证了输出的结构化数据是可靠且易于分析的，避免了模棱两可或自相矛盾的
