# GUI Transition Data Filter (IDM 数据清洗工具)

本脚本是一个基于**视觉大语言模型 (Vision Large Language Model, VLM)** 的移动端 GUI 交互数据自动化清洗工具。
其主要用于评估和筛选出高质量的 `(Before Screen, After Screen) -> Action` 数据对，以为训练**逆动力学模型 (Inverse Dynamics Model, IDM)** 准备高质量的数据集。

##  核心功能

-  **智能视觉分析**：结合前/后两张屏幕截图和动作指令，利用视觉大模型自动判断交互动作的有效性、因果关系及可学习性。
-  **高并发处理**：基于多线程 (`ThreadPoolExecutor`) 实现，大幅提升海量数据的处理速度。
-  **断点续传支持**：自动读取已生成的 CSV 文件，跳过已处理的数据，随时中断和恢复任务而不会丢失进度。
-  **高可用与容错**：内置 API 请求指数退避（Exponential Backoff）重试机制，从容应对网络抖动和 API 限流。
-  **全量 API 兼容**：支持任何兼容 OpenAI 接口格式的模型服务，包括但不限于 OpenRouter、本地部署的 vLLM。
-  **严格的结果结构化**：通过精心设计的 Prompt 强制模型输出标准 JSON 格式，并输出详细的评估理由和违规规则编号。

---

## 🛠️ 环境依赖

确保您的系统中已安装 Python。

安装所需依赖包：
```bash
pip install requests tqdm
```

---

##  数据集目录结构要求

程序会遍历配置的 `ROOT_DIR` 目录。您的原始数据集需遵循以下结构（通常为 DroidBot/Appium 抓取工具的输出格式）：

```text
/data/mv_trace_en/           <-- ROOT_DIR
├── AppName_1/
│   ├── utg.js               <-- 包含节点(nodes)和边(edges)的交互图数据
│   ├── screen_001.jpg       <-- 截图文件 (在 utg.js 中被引用)
│   ├── screen_002.jpg
│   └── ...
├── AppName_2/
│   ├── utg.js
│   ├── screen_A.jpg
│   └── ...
```
*注：代码会自动解析 `utg.js` 文件，提取状态节点映射，并寻找所有触发状态转移的 Action 及对应的两张图片。*

---

##  配置说明

在运行脚本前，请使用文本编辑器打开 Python 脚本，并修改开头的 `CONFIG` 字典配置：

### 1. 路径配置
- `ROOT_DIR`: 输入端原始数据集的根目录路径。
- `OUTPUT_CSV`: 输出端 CSV 文件的保存路径（支持断点续传）。
- `LOG_FILE`: 运行日志的保存路径，用于排查 API 错误或图片读取问题。

### 2. 模型 API 配置
- `API_KEY`: 您的 API 密钥。如果使用本地无需鉴权的服务（如本地 vLLM），可保持为空字符串 `""`。
- `API_URL`: 模型 API 的端点地址。
  - *OpenRouter 示例*: `https://openrouter.ai/api/v1/chat/completions`
  - *本地 vLLM 示例*: `http://localhost:8000/v1/chat/completions`
- `MODEL`: 调用的具体视觉模型名称（必须支持视觉输入，例如 `qwen/qwen3.5-397b-a17b`，或 `gpt-4o`, `llava` 等）。

### 3. 性能配置
- `MAX_WORKERS`: 多线程并发数（建议根据 API 并发限制和本地网络带宽调整，默认 `10`）。
- `REQUEST_TIMEOUT`: 单次 API 请求超时时间（单位：秒。视觉模型处理慢，建议 `>=60`）。
- `MAX_RETRIES`: 请求失败时的最大重试次数（默认 `3`）。

---

##  运行指南

配置完成后，直接运行 Python 脚本：

```bash
python filter_mv_trace.py
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
| `valid` | **最终判定**：`True` 表示样本合格，`False` 表示不合格 |
| `action_valid` | 动作有效性（是否为单一动作且目标可见） |
| `causal_correct` | 因果正确性（前后屏幕的变化是否由该动作引起） |
| `idm_learnable` | IDM 可学习性（UI 变化是否有意义、渲染是否完整） |
| `violations` | 触发的违规规则 ID 列表（合格样本为空 `[]`） |
| `reason` | 模型给出的判定理由（1-2句简述） |

---

##  评估规则 (Prompt 简介)

程序内置了严格的 Prompt，指导 VLM 执行以下判断。只有不触发任何否定规则的样本才会被标记为 `valid: True`：

**必须满足 (Positive Criteria):**
1. 动作必须明确、指向可见 UI 元素。
2. 动作必须导致明显的 UI 变化，且符合常理的交互因果关系。
3. 目标页面渲染完整（非加载中状态），且变化对于模型来说是“可学习”的。

**触发即废弃 (Negative Rules):**
- [Rule 1] 动作异常（空白、坐标越界、指向不可见区域）。
- [Rule 2] 涉及手机桌面的过渡（App 启动/退出/崩溃）。
- [Rule 3] 不符合常理的 UI 映射（如点击非破坏性按钮却弹出删除确认框）。
- [Rule 4] 动作失效（UI 毫无变化，或变化与动作毫不相干）。
- [Rule 5] 系统/后台干扰（弹出了系统权限框或收到后台通知）。
- [Rule 6] 毫无意义的变化（如仅时间改变、光标闪烁）。
- [Rule 7] 页面未加载完成（存在骨架屏、Loading 圈）。
- [Rule 8] 无效的滑动操作。

--- 
