## 过滤RIOC数据集的脚本工具

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
#### 效果示例
<p align="center">
<img src="image/35.jpg" width="600">
</p>
<p align="center">
<img src="image/image1.jpg" width="600">
</p>
<p align="center">
<img src="image/700.jpg" width="600">
</p>
<p align="center">
<img src="image/image.jpg" width="600">
</p>

### 三、下载filter_by_Gemini.py

