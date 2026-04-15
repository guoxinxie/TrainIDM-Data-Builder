import os
import glob

def check_missing_tasks(log_folder):
    """
    检查指定的日志文件夹中，是否包含了所有 138 个标准任务的 trace.jsonl
    """
    if not os.path.exists(log_folder):
        print(f"目录不存在: {log_folder}")
        return

    print(f"正在检查目录: {log_folder}")

    # 1. 获取所有标准任务的 ID (从 config 文件夹读取)
    config_folder = "./evaluation/config"
    expected_tasks = []
    
    if not os.path.exists(config_folder):
        print(f"找不到配置文件夹: {config_folder}，请在 AndroidLab 根目录运行此脚本。")
        return

    for yaml_file in glob.glob(os.path.join(config_folder, "*.yaml")):
        import yaml
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if 'tasks' in data:
                    for task in data['tasks']:
                        expected_tasks.append(task['task_id'])
        except Exception as e:
            print(f"读取 {yaml_file} 出错: {e}")

    print(f"总计应有任务数: {len(expected_tasks)}")

    # 2. 获取实际跑完的任务 ID
    # 假设你的日志目录结构是 logs/evaluation/agent_name/task_id_timestamp/traces/trace.jsonl
    actual_tasks = []
    for task_folder in os.listdir(log_folder):
        task_folder_path = os.path.join(log_folder, task_folder)
        if not os.path.isdir(task_folder_path):
            continue
            
        # 检查是否真的跑完了（有没有 trace.jsonl）
        trace_file = os.path.join(task_folder_path, "traces", "trace.jsonl")
        if os.path.exists(trace_file):
            # 从文件夹名(如 zoom_1_2024-...) 中提取前两部分作为 task_id (如 zoom_1)
            parts = task_folder.split("_")
            if len(parts) >= 2:
                task_id = f"{parts[0]}_{parts[1]}"
                actual_tasks.append(task_id)

    print(f"实际生成 trace 的任务数: {len(actual_tasks)}")

    # 3. 对比并找出缺失项
    missing_tasks = set(expected_tasks) - set(actual_tasks)
    
    if not missing_tasks:
        print("\n恭喜！所有 138 个任务都已成功生成 trace.jsonl。")
    else:
        print(f"\n发现 {len(missing_tasks)} 个缺失任务：")
        for mt in sorted(list(missing_tasks)):
            print(f"- {mt}")
            
        print("\n你可以使用以下命令重新运行这些缺失的任务：")
        missing_tasks_str = ",".join(missing_tasks)
        print(f"python eval.py -n <你的agent名称> -c <你的配置文件.yaml> --task_id {missing_tasks_str}")

# --- 运行示例 ---
# 替换为你实际想要检查的 agent 文件夹路径，例如:
# TARGET_DIR = "./logs/evaluation/qwen-3-vl-32b-mark"
import sys
if len(sys.argv) > 1:
    TARGET_DIR = sys.argv[1]
else:
    TARGET_DIR = input("请输入你要检查的 agent 日志文件夹路径 (例如 ./logs/evaluation/my_test): ")

check_missing_tasks(TARGET_DIR)