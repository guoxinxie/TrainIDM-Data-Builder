import csv
import json
import re
from collections import Counter
from pathlib import Path
from PIL import Image
from typing import Optional, Tuple
import math

# ================= Config =================
TRAIN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TRAIN_DIR.parent
INPUT_SPLIT_CSV = PROJECT_ROOT / "filtered_metadata_3rd" / "split.csv"
OUTPUT_JSON = TRAIN_DIR / "split_train_qwen25vl_sft.json"
TARGET_SPLIT = "train"
IMAGE_PREFIX = PROJECT_ROOT / "mv_trace_en"
HUMAN_PROMPT = """<image>
<image>
You are an expert mobile UI automation agent. You are given two screenshots of a mobile application:
- IMAGE 1: The UI state BEFORE an action is taken.
- IMAGE 2: The UI state AFTER an action is taken.

Your task is to deduce the single user action performed on IMAGE 1 that caused the transition to IMAGE 2.

### INSTRUCTIONS:
1. Compare IMAGE 1 and IMAGE 2. Identify what changed (e.g., a new menu opened, the screen scrolled, a button changed color, text was entered).
2. Locate the exact UI element in IMAGE 1 that was interacted with to cause this change.
3. Determine the coordinates (x, y) of the CENTER of that UI element in IMAGE 1.
4. If the screen scrolled, determine the direction. Note: "scroll down" means the page content moved up so that lower content became visible.

### ACTION SCHEMA:
Choose exactly ONE action from the following formats:
1. {"action_type": "click", "x": <integer>, "y": <integer>}
2. {"action_type": "input_text", "text": "<text>"}
3. {"action_type": "scroll", "direction": "up" | "left" | "right" | "down"}
4. {"action_type": "navigate_back"}
5. {"action_type": "long_press", "x": <integer>, "y": <integer>}
6. {"action_type": "wait"}

### OUTPUT:
Output the precise action in a standard JSON code block.
"""

# copy from: qwen2.5vl vision_process.py
MAX_RATIO = 200
SPATIAL_MERGE_SIZE = 2
IMAGE_MIN_TOKEN_NUM = 4
IMAGE_MAX_TOKEN_NUM = 16384
FACTOR = 28

def round_by_factor(number: int, factor: int) -> int:
    """Returns the closest integer to 'number' that is divisible by 'factor'."""
    return round(number / factor) * factor


def ceil_by_factor(number: int, factor: int) -> int:
    """Returns the smallest integer greater than or equal to 'number' that is divisible by 'factor'."""
    return math.ceil(number / factor) * factor


def floor_by_factor(number: int, factor: int) -> int:
    """Returns the largest integer less than or equal to 'number' that is divisible by 'factor'."""
    return math.floor(number / factor) * factor

def smart_resize(height: int, width: int, factor: int = FACTOR, min_pixels: Optional[int] = None, max_pixels: Optional[int] = None) -> Tuple[int, int]:
    """
    Rescales the image so that the following conditions are met:

    1. Both dimensions (height and width) are divisible by 'factor'.
    2. The total number of pixels is within the range ['min_pixels', 'max_pixels'].
    3. The aspect ratio of the image is maintained as closely as possible.
    """
    max_pixels = max_pixels if max_pixels is not None else (IMAGE_MAX_TOKEN_NUM * factor ** 2)
    min_pixels = min_pixels if min_pixels is not None else (IMAGE_MIN_TOKEN_NUM * factor ** 2)
    assert max_pixels >= min_pixels, "The max_pixels of image must be greater than or equal to min_pixels."
    if max(height, width) / min(height, width) > MAX_RATIO:
        raise ValueError(
            f"absolute aspect ratio must be smaller than {MAX_RATIO}, got {max(height, width) / min(height, width)}"
        )
    h_bar = max(factor, round_by_factor(height, factor))
    w_bar = max(factor, round_by_factor(width, factor))
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = floor_by_factor(height / beta, factor)
        w_bar = floor_by_factor(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = ceil_by_factor(height * beta, factor)
        w_bar = ceil_by_factor(width * beta, factor)
    return h_bar, w_bar

# ----------------------------------------------------------------------

def parse_action_type(action_text):
    m = re.match(r"^\s*([a-z_]+)", action_text.lower())
    return m.group(1) if m else ""


def parse_bbox_center(action_text, image_path):
    m = re.search(
        r"(?:bound_box|bounding_box|bbox)\s*=\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)",
        action_text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None

    x1, y1, x2, y2 = [int(m.group(i)) for i in range(1, 5)]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    x_pixel = int((left + right) / 2)
    y_pixel = int((top + bottom) / 2)
    
    with Image.open(image_path) as img:
        width, height = img.size

    if width <= 0 or height <= 0:
        return None

    resized_h, resized_w = smart_resize(height, width)
    x = int(round(x_pixel / width * resized_w))
    y = int(round(y_pixel / height * resized_h))

    return x, y


def parse_scroll_direction(action_text):
    m = re.search(r"direction\s*=\s*(up|down|left|right)", action_text, flags=re.IGNORECASE)
    if m:
        return m.group(1).lower()

    m = re.search(r"^\s*scroll(?:\s*:)?\s*(up|down|left|right)\b", action_text, flags=re.IGNORECASE)
    if m:
        return m.group(1).lower()

    return None


def parse_set_text_value(action_text):
    m = re.search(r"text\s*=\s*(.*?)(?:\)\s*$|$)", action_text, flags=re.IGNORECASE)
    if m:
        text = m.group(1).strip()
        if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
            text = text[1:-1]
        return text

    # Alternative format example:
    # set_text <input ...>Label</input> dummy_user_input
    # Keep only the trailing input text after the closing element tag.
    m = re.search(r"</[^>]+>\s*(.+)$", action_text, flags=re.IGNORECASE)
    if m:
        text = m.group(1).strip()
        if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
            text = text[1:-1]
        return text

    m = re.search(r"set_text\b[:\s]+(.+)$", action_text, flags=re.IGNORECASE)
    if m:
        text = m.group(1).strip()
        if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
            text = text[1:-1]
        return text

    return ""


def convert_action(action_text, before_image_path):
    action_type = parse_action_type(action_text)

    if action_type in {"intent", "kill_app"}:
        return None

    if action_type in {"touch", "select", "unselect"}:
        center = parse_bbox_center(action_text, before_image_path)
        if not center:
            return None
        x, y = center
        return {"action_type": "click", "x": x, "y": y}

    if action_type == "scroll":
        direction = parse_scroll_direction(action_text)
        if not direction:
            return None
        reverse = {"up": "down", "down": "up", "left": "right", "right": "left"}
        return {"action_type": "scroll", "direction": reverse[direction]}

    if action_type == "set_text":
        text = parse_set_text_value(action_text)
        return {"action_type": "input_text", "text": text}

    if action_type == "long_touch":
        center = parse_bbox_center(action_text, before_image_path)
        if not center:
            return None
        x, y = center
        return {"action_type": "long_press", "x": x, "y": y}

    if action_type == "wait_user_login":
        return {"action_type": "wait"}

    return None


def main():
    dataset = []
    stats = Counter()
    skipped = Counter()

    input_csv = Path(INPUT_SPLIT_CSV)
    output_json = Path(OUTPUT_JSON)
    image_prefix = Path(IMAGE_PREFIX)

    with open(input_csv, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("split") != TARGET_SPLIT:
                continue

            raw_action = (row.get("action") or "").strip()
            source_action_type = parse_action_type(raw_action) or "unknown"

            app_name = row["app_name"]
            from_screen = row["from_screen_filename"]
            to_screen = row["to_screen_filename"]

            before_image_path = image_prefix / app_name / "states" / from_screen
            after_image_path = image_prefix / app_name / "states" / to_screen

            mapped_action = convert_action(raw_action, before_image_path)
            if mapped_action is None:
                skipped[source_action_type] += 1
                continue

            app_name = row["app_name"]
            from_screen = row["from_screen_filename"]
            to_screen = row["to_screen_filename"]

            sample = {
                "image": [
                    str(before_image_path.as_posix()),
                    str(after_image_path.as_posix()),
                ],
                "conversations": [
                    {
                        "from": "human",
                        "value": HUMAN_PROMPT,
                    },
                    {
                        "from": "gpt",
                        "value": json.dumps(mapped_action, ensure_ascii=False),
                    },
                ],
            }
            dataset.append(sample)
            stats[mapped_action["action_type"]] += 1

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"Input CSV: {input_csv}")
    print(f"Target split: {TARGET_SPLIT}")
    print(f"Generated samples: {len(dataset)}")
    print(f"Output JSON: {output_json}")
    print("Mapped action stats:")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    if skipped:
        print("Skipped source action stats:")
        for k in sorted(skipped):
            print(f"  {k}: {skipped[k]}")


if __name__ == "__main__":
    main()
