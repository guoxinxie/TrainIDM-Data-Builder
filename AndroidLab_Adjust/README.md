# AndroidLab: JSON Vision Agent 扩展指南

本文档介绍了对 AndroidLab 框架的扩展，使其能够原生支持直接输出结构化 JSON 动作指令的多模态大模型（如 Qwen2.5-VL、Qwen3-VL 等）。

AndroidLab 多模态评估流程（如 `ScreenshotTask`）通常依赖模型输出特定格式的单行 Python 代码（如 `tap(1)` 或 `swipe("up")`）。本次扩展允许模型直接观察**无标记（Unlabeled）的原始屏幕截图**，并输出更通用、更易解析的 JSON 格式动作，随后框架会自动将这些 JSON 动作安全地映射并转换为底层执行器（Executor）可执行的代码。


## 架构设计

扩展涉及三个核心组件：

1.  **Prompt Template (提示词模板)**：定义在 `templates/android_screenshot_template.py` 中。明确规定了模型需要输出的 JSON 格式、动作类型以及坐标系规则（像素 vs 归一化）。
2.  **Agent Task (任务处理器)**：定义在 `evaluation/evaluation.py` 中。负责拼接 Prompt、调用模型 API、接收 JSON 字符串，并将其**转换（Translate）** 为执行器可识别的 Python 代码。
3.  **AutoTest Class (测试启动器)**：定义在 `evaluation/auto_test.py` 中。负责组装 Agent 和 Executor，并注册到配置系统中供 `eval.py` 调用。

## 3. 支持的模型与使用方法

### 3.1 Qwen2.5-VL (使用绝对像素坐标)

Qwen2.5-VL 被配置为输出与设备真实分辨率一致的绝对像素坐标。

**依赖类**:
*   Task: `OriginalImageJSONVisionTask_Qwen2_5_vl` (位于 `evaluation.py`)
*   AutoTest: `OriginalImageJSONTask_AutoTest_Qwen2_5_vl` (位于 `auto_test.py`)
*   Prompt: `SYSTEM_PROMPT_QWEN2_5_VL_IMAGE_JSON`

**配置文件 (`config.yaml`) 示例**:
```yaml
agent:
    name: OpenAIAgent  # 或其他兼容 OpenAI API 格式的 Agent 类
    args:
        api_key: "your_api_key"
        api_base: "http://localhost:8000/v1"  # vLLM 部署地址
        model_name: "Qwen2.5-VL-7B-Instruct"          
        max_new_tokens: 512
        temperature: 0.0

task:
    class: OriginalImageJSONTask_AutoTest_Qwen2_5_vl  # 使用专用的启动类
    args:
        save_dir: "./logs/evaluation"
        max_rounds: 25
        request_interval: 15
        mode: "in_app"

eval:
  avd_name: Pixel_7_Pro_API_33
  # ... 其他 AVD 配置
```
| **`ScreenshotMobileTask_AutoTest`** | 带数字标签的截图 (SoM) | `tap(index)` 等Python代码 | 经典 SoM 范式，指代明确 |(**set of mark主要**)
| **`OriginalImageJSONTask_AutoTest_*`** | **原始截图** | JSON 对象（含坐标） | **无标签视觉**，输出结构化，框架智能映射 |(**set of coordinate主要**)
| **`ScreenReactTask_AutoTest`** | 带数字标签的截图 (SoM) | `Thought` + `Action` | SoM + 思维链，可解释性强 |
| **`ScreenSeeActTask_AutoTest`** | 带数字标签的截图 (SoM) | 两阶段：自然语言描述 -> `do()` | 模仿“看-指”过程，流程复杂 |

### 3.2 Qwen3-VL (使用 0-1000 归一化坐标)

Qwen3-VL 原生输出 0-1000 的归一化坐标，框架会根据运行时获取的屏幕宽高动态转换。

**依赖类**:
*   Task: `OriginalImageJSONVisionTask_Qwen3_vl` (位于 `evaluation.py`)
*   AutoTest: `OriginalImageJSONTask_AutoTest_Qwen3_vl` (位于 `auto_test.py`)
*   Prompt: `SYSTEM_PROMPT_QWEN3_VL_IMAGE_JSON`

**配置文件 (`config.yaml`) 示例**:
```yaml
# ... (agent 配置相同，更改 model_name 即可)
task:
    class: OriginalImageJSONTask_AutoTest_Qwen3_vl  # 使用 Qwen3 专用的启动类
    # ...
```

## 动作空间 (Action Space) 映射参考

模型输出的 JSON 被解析后，将映射为 `VisionExecutor` 的以下方法：

| 模型输出 JSON (示例) | 映射到 VisionExecutor 的代码 | 说明 |
| :--- | :--- | :--- |
| `{"action_type": "click", "x": 540, "y": 1000}` | `tap(index)` 或 `self.controller.tap(x,y)` | 优先根据坐标在 UI 树中查找最近的控件索引。如果找不到，退化为使用控制器的原生绝对坐标点击。 |
| `{"action_type": "long_press", "x": 100, "y": 200}` | `long_press(index)` 或 `self.controller.long_press(x,y)`| 同上，优先匹配控件索引。 |
| `{"action_type": "input_text", "text": "Hello"}` | `type(input_str="Hello")` | 输入文本。建议模型在输入前先 click 激活输入框。 |
| `{"action_type": "scroll", "direction": "down"}` | `swipe(direction='up', dist='long')` | 模型输出的是“向下看”的内容方向，框架会自动将其反转为手机屏幕的滑动方向（上滑）。 |
| `{"action_type": "navigate_home"}` | `home()` | 返回桌面。 |
| `{"action_type": "navigate_back"}` | `back()` | 返回上一级。 |
| `{"action_type": "wait"}` | `wait()` | 等待（为 5 秒）。当解析失败或坐标越界时，框架也会默认触发 `wait()` 以保证流程不中断。 |
| `{"action_type": "finish", "message": "done"}`| `finish(message="done")` | 标记任务完成，终止测试。 |


# 快速开始
## 1.下载 Android-Lab的整个项目
* **链接**: [https://github.com/THUDM/Android-Lab/tree/main](https://github.com/THUDM/Android-Lab/tree/main)
## 2.安装依赖
```bash
cd /path/to/your/repo
conda create -n Android-Lab python=3.11
conda activate Android-Lab
pip install -r requirements.txt
```
## 3.确保您有 KVM 和 Docker
请点击以下链接下载相关 Docker 文件 [https://drive.google.com/file/d/1SJ79gdO7whgUod3HnuS87aOKihRk1i-U/view?usp](https://drive.google.com/file/d/1SJ79gdO7whgUod3HnuS87aOKihRk1i-U/view?usp)
因为Android-Lab Docker镜像版本久远，建议配置在我的仓库中你只需下载 **Dockerfile**替换掉原来的配置文件
```bash
mkdir docker_file
cd docker_file
unzip /path/to/your/docker-file.zip
cd docker-file
docker build -t android_eval:latest .

```
建议换阿里的镜像或者清华的镜像

## 4.替换文件
* **./docker_file/docker-file/Dockerfile**
* **./evaluation/auto_test.py、evaluation.py、definition.py**
* **./templates/android_screenshot_template.py**
* **./page_executor/simple_vision_executor.py和text_executor.py**
* **./agent/model.py**
* **./adb_client.py**
* **./tools/check_result_multiprocess.py**
## 5.修改配置文件
将qwen-2.5-vl-linux.yaml，qwen-3-vl-linux.yaml加入到./configs中并修改相应的模型名称，apikey等参数

## 6.执行命令
测试一个任务或多个任务
```bash
python eval.py \
  -n test1 \
  -c ./configs/qwen-2.5-vl-linux.yaml\
  --task_id zoom_1
```
```bash
python eval.py \
  -n test1 \
  -c ./configs/qwen-2.5-vl-linux.yaml\
  --task_id clock_1 bluecoins_1 calendar_1 cantook_1 contacts_1 map_1 pimusic_1 setting_0 zoom_1
```

没问题就可以开始评测模型
```bash
python eval.py \
  -n test \
  -c ./configs/qwen-2.5-vl-linux.yaml
```（跑完一个模型138个任务约12个小时）
或者
```bash
python eval.py \
  -n test \
  -c ./configs/qwen-2.5-vl-linux.yaml \
  -p 3
```（跑完一个模型138个任务约5个小时）
评测模型
```bash
# gpt-4o-2024-05-13评测(需要挂vpn):
python generate_result.py \
    --input_folder ./logs/evaluation/ \
    --output_folder ./outputs/ \
    --output_excel ./outputs/test_result_gpt4o.xlsx \
    --judge_model openai/gpt-4o \
    --api_base https://openrouter.ai/api/v1 \
    --api_key "your-api-key-here"
```
```bash
# 人工验证模型轨迹
python tools/check_result_multiprocess.py \
    --directory_path ./logs/evaluation \
    --save_path ./outputs/visual_results

```
## 引用与致谢 (References & Acknowledgements)
```bibtex

@misc{xu2024androidlabtrainingsystematicbenchmarking,
      title={AndroidLab: Training and Systematic Benchmarking of Android Autonomous Agents}, 
      author={Yifan Xu and Xiao Liu and Xueqiao Sun and Siyi Cheng and Hao Yu and Hanyu Lai and Shudan Zhang and Dan Zhang and Jie Tang and Yuxiao Dong},
      year={2024},
      eprint={2410.24024},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2410.24024}, 
}
```
