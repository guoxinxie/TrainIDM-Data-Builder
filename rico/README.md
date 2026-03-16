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
  -剔除原因：筛选后navigate_home: 1，且样本没有底部导航栏。
- Scroll: 多点触摸且首尾位移大于屏幕尺寸的 1%（0.01）。
- Long Press: 多点触摸但首尾位移极小（小于屏幕尺寸的 1%）。

