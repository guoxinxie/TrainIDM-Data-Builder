import json
import math
import os
from multiprocessing import Pool

import chardet
import jsonlines
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from PIL import Image, ImageDraw
from tqdm import tqdm

#plt.rcParams['font.sans-serif'] = ['SimHei']
#plt.rcParams['axes.unicode_minus'] = False


def draw_cross_on_image(img, coordinates):
    draw = ImageDraw.Draw(img)
    x, y = coordinates
    cross_length = 100
    line_width = 20
    draw.line((x - cross_length // 2, y, x + cross_length // 2, y), fill="green", width=line_width)
    draw.line((x, y - cross_length // 2, x, y + cross_length // 2), fill="green", width=line_width)
    return img


def draw_arrow_on_image(img, start, end):
    draw = ImageDraw.Draw(img)
    arrow_length = 50
    arrow_angle = math.pi / 6
    draw.line([start, end], fill="green", width=10)
    angle = math.atan2(end[1] - start[1], end[0] - start[0]) + math.pi
    arrow_point1 = (
        end[0] + arrow_length * math.cos(angle - arrow_angle), end[1] + arrow_length * math.sin(angle - arrow_angle))
    arrow_point2 = (
        end[0] + arrow_length * math.cos(angle + arrow_angle), end[1] + arrow_length * math.sin(angle + arrow_angle))
    draw.polygon([end, arrow_point1, arrow_point2], fill="green")
    return img


def create_text_image(text, base_image, font_size=24, log_path=None):
    if log_path is None:
        log_path = '..'
    text_image_path = os.path.join(log_path, 'text_image.png')

    base_width, base_height = base_image.size

    # --- 核心修改：指定字体文件的绝对路径 ---
    # 请将下面的路径替换为你实际上传的字体文件的路径
    font_path = '/data/xgx/AndroidLab/tools/fonts/SIMHEI.TTF' 
    
    # 检查字体文件是否存在，如果存在则使用它，否则退回默认（防崩溃）
    if os.path.exists(font_path):
        my_font = FontProperties(fname=font_path, size=font_size)
    else:
        print(f"[警告] 找不到字体文件: {font_path}，将使用默认字体(可能无法显示中文)")
        my_font = FontProperties(size=font_size)

    plt.rcParams['savefig.transparent'] = True

    width = base_width / 100
    height = (base_height / 10) / 100
    dpi = 100
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    
    # --- 核心修改：在绘制文本时应用指定的字体属性 (fontproperties=my_font) ---
    ax.text(0.5, 0.5, text, ha='center', va='center', transform=ax.transAxes, color='red', fontproperties=my_font)
    
    ax.axis('off')
    fig.savefig(text_image_path, format='png', transparent=True)
    plt.close(fig)

    return text_image_path


def merge_text(img, text_image, position=(0, 0)):
    base_image = img
    text_image = Image.open(text_image).convert("RGBA")
    base_width, base_height = base_image.size
    new_text_height = base_height // 10
    text_image_resized = text_image.resize((base_width, new_text_height))
    new_image = Image.new("RGBA", base_image.size)
    new_image.paste(base_image, (0, 0))
    new_image.paste(text_image_resized, position, text_image_resized)
    return new_image


def merge_text_up(img, text_image, position=(0, 0)):
    base_image = img
    text_image = Image.open(text_image).convert("RGBA")
    base_width, base_height = base_image.size
    new_text_height = base_height // 10
    text_image_resized = text_image.resize((base_width, new_text_height))

    new_image_height = base_height + new_text_height
    new_image = Image.new("RGBA", (base_width, new_image_height))

    new_image.paste(text_image_resized, position)
    base_image_position = (0, new_text_height)
    new_image.paste(base_image, base_image_position)

    return new_image


def merge_images(images):
    total_area = sum(im.size[0] * im.size[1] for im in images)
    max_width = max(im.size[0] for im in images)
    max_height = max(im.size[1] for im in images)

    side_length = int((total_area) ** 0.5)

    cols = max(max_height, side_length) // min(max_height, max_width)
    if cols == 0: cols = 1
    rows = len(images) // cols + (1 if len(images) % cols > 0 else 0)

    total_width = max_width * cols
    total_height = max_height * rows

    new_im = Image.new('RGBA', (total_width, total_height))

    x_offset = 0
    y_offset = 0
    for i, im in enumerate(images):
        if x_offset + im.size[0] > total_width:
            x_offset = 0
            y_offset += max_height

        new_im.paste(im, (x_offset, y_offset))
        x_offset += im.size[0]

        if (i + 1) % cols == 0:
            x_offset = 0
            y_offset += max_height

    return new_im


def make_merge_pic(log_path, save_path=None):
    trace_file = os.path.join(log_path, "traces", "trace.jsonl")
    all_images = []
    task_description = None

    if not os.path.exists(trace_file):
        return

    with open(trace_file, 'r', encoding='utf-8') as f:
        for obj in f:
            obj = json.loads(obj)
            if task_description is None:
                task_description = obj["prompt"]
            img_path_orgin = obj["image"]
            image_filename = os.path.basename(img_path_orgin)
            image_path = os.path.join(log_path, "Screen", image_filename)
            
            if not os.path.exists(image_path):
                continue
                
            img = Image.open(image_path)
            window = obj["window"]
            if img.size != window:
                if img.size[0] == window[1] and img.size[1] == window[0]:
                    img = img.rotate(270, expand=True)
            
            parsed_action = obj.get("parsed_action", {})
            action = parsed_action.get("action", "")
            kwargs = parsed_action.get("kwargs", {})
            processed_img = None

            # === 修复 1：处理坐标长度问题 ===
            if action in ["Tap", "Long Press"]:
                element = kwargs.get("element", [])
                if isinstance(element, list) and len(element) == 4:
                    start_pos = ((element[0] + element[2]) / 2, (element[1] + element[3]) / 2)
                elif isinstance(element, (list, tuple)) and len(element) == 2:
                    start_pos = (element[0], element[1])
                else:
                    start_pos = (img.width / 2, img.height / 2)
                processed_img = draw_cross_on_image(img, start_pos)

            elif action == "Swipe":
                element = kwargs.get("element", [])
                if isinstance(element, list) and len(element) == 4:
                    start_pos = ((element[0] + element[2]) / 2, (element[1] + element[3]) / 2)
                elif isinstance(element, (list, tuple)) and len(element) == 2:
                    start_pos = (element[0], element[1])
                else:
                    start_pos = (img.width / 2, img.height / 2)
                
                direction = kwargs.get("direction", "up")
                if direction == "up":
                    end_pos = (start_pos[0], start_pos[1] - 100)
                elif direction == "down":
                    end_pos = (start_pos[0], start_pos[1] + 100)
                elif direction == "left":
                    end_pos = (start_pos[0] - 100, start_pos[1])
                elif direction == "right":
                    end_pos = (start_pos[0] + 100, start_pos[1])
                else:
                    end_pos = start_pos
                processed_img = draw_arrow_on_image(img, start_pos, end_pos)

            elif action == "Type":
                text = f"{action}: {kwargs.get('text', '')}"
                text_img = create_text_image(text, img, 48, log_path=log_path)
                processed_img = merge_text(img, text_img, position=(0, 0))

            elif action in ["Back", "Press Back"]:
                text = "Press Back"
                text_img = create_text_image(text, img, 48, log_path=log_path)
                processed_img = merge_text(img, text_img, position=(0, 0))

            elif action == "Launch":
                text = f"Launch: {kwargs.get('app_name', kwargs.get('package', ''))}"
                text_img = create_text_image(text, img, 48, log_path=log_path)
                processed_img = merge_text(img, text_img, position=(0, 0))
                
            elif action == "Wait":
                text = "Wait"
                text_img = create_text_image(text, img, 48, log_path=log_path)
                processed_img = merge_text(img, text_img, position=(0, 0))

            # === 修复 3：修复路径重复拼接 Bug ===
            elif action == "finish":
                screens = os.listdir(os.path.join(log_path, "Screen"))
                end_image_filename = image_filename
                for screen in screens:
                    if "end" in screen:
                        end_image_filename = screen
                        break
                
                end_image_path = os.path.join(log_path, "Screen", end_image_filename)
                if os.path.exists(end_image_path):
                    img = Image.open(end_image_path)
                
                text = f"finish: {kwargs.get('message', '')}"
                text_img = create_text_image(text, img, 48, log_path=log_path)
                processed_img = merge_text(img, text_img, position=(0, 0))

            # === 修复 2：防止 UnboundLocalError ===
            else:
                # 当遇到未定义的操作（如 ExecutionError）时，直接绘制文字
                text = f"Unknown Action: {action}"
                text_img = create_text_image(text, img, 48, log_path=log_path)
                processed_img = merge_text(img, text_img, position=(0, 0))

            if processed_img:
                all_images.append(processed_img)

    if not all_images:
        return

    final_image = merge_images(all_images)
    task_description = str(task_description).split("following task: ")[-1]
    text_img = create_text_image("Task: " + task_description, final_image, 48, log_path=log_path)
    final_image = merge_text_up(final_image, text_img, position=(0, 0))
    
    if save_path is None:
        save_path = log_path
    else:
        if not os.path.exists(save_path):
            os.makedirs(save_path)
            
    filename = os.path.basename(log_path)
    final_image_path = os.path.join(save_path, f"{filename}_final_combined_image.png")
    final_image.save(final_image_path)


def single_worker(all_log_path, log, save_path):
    try:
        log_path = os.path.join(all_log_path, log)
        make_merge_pic(log_path, save_path)
    except Exception as e:
        pass # Ignore printing tracebacks to keep console clean for progress bar


def check_all_log(all_log_path, save_path=None):
    def err_call_back(err):
        pass

    with Pool(processes=20) as pool: # 降低进程数防止图片处理时爆内存
        for log in tqdm(os.listdir(all_log_path)):
            pool.apply_async(single_worker, args=(all_log_path, log, save_path,), error_callback=err_call_back)
        pool.close()
        pool.join()


if __name__ == '__main__':
    import argparse
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--directory_path", default="logs/evaluation", type=str)
    arg_parser.add_argument("--save_path", default="logs/pic", type=str)

    directory_path = arg_parser.parse_args().directory_path
    save_path = arg_parser.parse_args().save_path

    subfolders = [f.name for f in os.scandir(directory_path) if f.is_dir()]

    combined_paths = [os.path.join(directory_path, subfolder) for subfolder in subfolders]
    combined_save_paths = [os.path.join(save_path, subfolder) for subfolder in subfolders]

    for all_log_path, save_path_item in zip(combined_paths, combined_save_paths):
        check_all_log(all_log_path, save_path_item)
