# IDM Agent Evaluation

本目录包含三个 agent，其中 none-cot 沿用之前版本中 agent.py 的逻辑：

| CLI 名称 | 文件 | 输出方式 | Evaluation |
| --- | --- | --- | --- |
| `cot` | `agent-cot.py` | 显式 CoT，然后输出像素 action JSON | 像素坐标评估 |
| `none-cot` | `agent-none-cot.py` | 直接输出像素 action JSON | 像素坐标评估 |
| `som` | `agent-som.py` | 直接输出 component index action JSON | 直接比较 component index |

以下命令均从 `MobileViews/filter` 目录运行：

```bash
cd /path/to/TrainIDM-Data-Builder/MobileViews/filter
python3 -m pip install requests pillow tqdm
```

SoM 要求 before screenshot 旁边存在对应的 view hierarchy，例如：

```text
screen_12.jpg -> state_12.json
```

## 使用 OpenRouter

设置 OpenRouter API key 和多模态模型：

```bash
export API_URL="https://openrouter.ai/api/v1/chat/completions"
export API_KEY="<openrouter-api-key>"
export MODEL="<openrouter-multimodal-model-slug>"
```

运行三个 agent：

```bash
python3 eval/eval.py --agent cot --output-csv openrouter_run.csv
python3 eval/eval.py --agent none-cot --output-csv openrouter_run.csv
python3 eval/eval.py --agent som --output-csv openrouter_run.csv
```

结果分别保存到：

```text
eval/outputs/cot/openrouter_run.csv
eval/outputs/none-cot/openrouter_run.csv
eval/outputs/som/openrouter_run.csv
```

## 使用本地 vLLM

启动支持图片输入的本地模型：

```bash
vllm serve <vision-model-or-local-path> \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name mobile-vlm
```

设置本地 endpoint：

```bash
export API_URL="http://127.0.0.1:8000/v1/chat/completions"
export API_KEY=""
export MODEL="mobile-vlm"
```

运行三个 agent：

```bash
python3 eval/eval.py --agent cot --output-csv local_vllm_run.csv
python3 eval/eval.py --agent none-cot --output-csv local_vllm_run.csv
python3 eval/eval.py --agent som --output-csv local_vllm_run.csv
```

结果分别保存到：

```text
eval/outputs/cot/local_vllm_run.csv
eval/outputs/none-cot/local_vllm_run.csv
eval/outputs/som/local_vllm_run.csv
```

## Evaluation

`eval.py` 会在模型推理完成后立即执行对应的 evaluation：

- `cot` 和 `none-cot` 使用原有像素坐标评估。
- `som` 直接比较预测 component index 与 ground-truth component index，不把 index 转换为坐标。

因此，上面的 agent 命令执行完成后，输出 CSV 已经包含：

```text
action_type_match
exact_action_match
```

SoM CSV 还包含：

```text
ground_truth_component_indices
predicted_component_index
```

### 重新评估已有输出

如果输出 CSV 已存在，再次运行相同命令且不指定 `-n`，程序会跳过模型推理，只重新计算
evaluation 字段。

OpenRouter 结果：

```bash
python3 eval/eval.py --agent cot --output-csv openrouter_run.csv
python3 eval/eval.py --agent none-cot --output-csv openrouter_run.csv
python3 eval/eval.py --agent som --output-csv openrouter_run.csv
```

本地 vLLM 结果：

```bash
python3 eval/eval.py --agent cot --output-csv local_vllm_run.csv
python3 eval/eval.py --agent none-cot --output-csv local_vllm_run.csv
python3 eval/eval.py --agent som --output-csv local_vllm_run.csv
```

看到以下输出表示使用了已有预测，没有重新调用模型：

```text
Skipped model inference. Re-evaluated using cached predictions.
```

如果首次运行使用了采样参数，例如：

```bash
python3 eval/eval.py --agent som -n 1000 -s 91010 --output-csv som_1000.csv
```

重新评估该 CSV 时需要去掉 `-n`：

```bash
python3 eval/eval.py --agent som --output-csv som_1000.csv
```

### 生成 HTML 预览

例如为三个 OpenRouter 结果生成预览：

```bash
python3 eval/generate_eval_preview.py \
  --csv eval/outputs/cot/openrouter_run.csv \
  --output eval/outputs/cot/openrouter_run_preview.html

python3 eval/generate_eval_preview.py \
  --csv eval/outputs/none-cot/openrouter_run.csv \
  --output eval/outputs/none-cot/openrouter_run_preview.html

python3 eval/generate_eval_preview.py \
  --csv eval/outputs/som/openrouter_run.csv \
  --output eval/outputs/som/openrouter_run_preview.html
```
