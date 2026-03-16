import os
import json
from PIL import Image, ImageDraw
import shutil

# =============================
# 配置
# =============================

rico_root = "/data/filtered_traces"

output_root = "/data/screenshots_jpg"

os.makedirs(output_root, exist_ok=True)

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

# 点大小
POINT_RADIUS = 12


# =============================
# 画手势
# =============================

def draw_gesture(img, points):

    draw = ImageDraw.Draw(img)
    w, h = img.size

    pixel_points = []

    for p in points:

        if not isinstance(p, list) or len(p) != 2:
            continue

        x = int(p[0] * w)
        y = int(p[1] * h)

        pixel_points.append((x, y))

    if len(pixel_points) == 0:
        return img

    r = POINT_RADIUS

    # click
    if len(pixel_points) == 1:

        x, y = pixel_points[0]

        draw.ellipse((x-r-2, y-r-2, x+r+2, y+r+2), fill="black")
        draw.ellipse((x-r, y-r, x+r, y+r), fill="blue")

    # swipe
    else:

        # 轨迹
        draw.line(pixel_points, fill="blue", width=4)

        # 起点
        sx, sy = pixel_points[0]
        draw.ellipse((sx-r, sy-r, sx+r, sy+r), fill="green")

        # 终点
        ex, ey = pixel_points[-1]
        draw.ellipse((ex-r, ey-r, ex+r, ey+r), fill="red")

    return img


# =============================
# 主程序
# =============================

def extract_images():

    total = 0

    for root, dirs, files in os.walk(rico_root):

        if os.path.basename(root) != "screenshots":
            continue

        trace_dir = os.path.dirname(root)
        gestures_path = os.path.join(trace_dir, "gestures.json")

        gestures = {}

        if os.path.exists(gestures_path):

            try:
                with open(gestures_path, "r", encoding="utf-8") as f:
                    gestures = json.load(f)

                dst_gesture = os.path.join(os.path.dirname(output_dir), "gestures.json")

                if not os.path.exists(dst_gesture):
                    shutil.copy2(gestures_path, dst_gesture)
                    print("Copied gesture:", dst_gesture)

            except Exception as e:
                print("Gesture processing error:", e)

        # ===== 创建对应输出目录（保持原目录结构）=====
        relative_path = os.path.relpath(root, rico_root)
        output_dir = os.path.join(output_root, relative_path)

        os.makedirs(output_dir, exist_ok=True)

        print("Processing:", root)

        for img_name in files:

            # 跳过 macOS 文件
            if img_name.startswith("._"):
                continue

            if not img_name.lower().endswith(IMG_EXT):
                continue

            img_path = os.path.join(root, img_name)

            try:

                img = Image.open(img_path).convert("RGB")

                name = os.path.splitext(img_name)[0]

                if name in gestures and isinstance(gestures[name], list):

                    img = draw_gesture(img, gestures[name])

                save_path = os.path.join(output_dir, name + ".jpg")

                img.save(save_path, "JPEG", quality=95)

                total += 1

            except Exception as e:
                print("Error:", img_path, e)

    print(f"\nFinished! Extracted {total} images")


if __name__ == "__main__":
    extract_images()
