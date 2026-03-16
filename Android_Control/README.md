# Android UI 多模态微调数据处理工具

本工具用于将 Android_Control控制数据集（TFRecord 格式）解析、提取并转换为 **多模态大语言模型（如 Qwen-VL）微调所需的数据格式**。

脚本可提取“操作前截图”和“操作后截图”，并构造问答对，要求模型根据两张图的差异输出导致状态变化的动作（Action JSON）。

##  核心特性

- **自动提取图片**：从 TFRecord 的二进制数据中提取截图，并按任务 ID (`episode_id`) 分类保存为本地 PNG 文件。
- **断点跳过**：若图片目录已存在，则自动跳过图片保存步骤，加快调试和重复运行的效率。
- **Qwen-VL 格式兼容**：默认生成支持多图输入的 `Human-GPT` 格式微调 JSON。
- **动作统计监控**：在终端自动输出 `click`, `scroll`, `input_text` 等动作的统计分布，便于数据不平衡分析。

##  环境依赖

请确保您的 Python 环境中安装了以下依赖：

```bash
pip install tensorflow pillow
