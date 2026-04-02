import csv
import json
import re
from collections import Counter

# ================= Config =================
INPUT_SPLIT_CSV = "split.csv"
OUTPUT_JSON = "split_train_qwenvl.json"
TARGET_SPLIT = "train"
IMAGE_PREFIX = "./mv_trace_en"
HUMAN_PROMPT = (
    "<image>\n"
    "<image>\n"
    "Observe the two screenshots before and after. Output the action JSON that caused this state change."
)


def parse_action_type(action_text):
    m = re.match(r"^\s*([a-z_]+)", action_text.lower())
    return m.group(1) if m else ""


def parse_bbox_center(action_text):
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
    x = int((left + right) / 2)
    y = int((top + bottom) / 2)
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


def convert_action(action_text):
    action_type = parse_action_type(action_text)

    if action_type in {"intent", "kill_app"}:
        return None

    if action_type in {"touch", "select", "unselect"}:
        center = parse_bbox_center(action_text)
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
        center = parse_bbox_center(action_text)
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

    with open(INPUT_SPLIT_CSV, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("split") != TARGET_SPLIT:
                continue

            raw_action = (row.get("action") or "").strip()
            mapped_action = convert_action(raw_action)
            source_action_type = parse_action_type(raw_action) or "unknown"
            if mapped_action is None:
                skipped[source_action_type] += 1
                continue

            app_name = row["app_name"]
            from_screen = row["from_screen_filename"]
            to_screen = row["to_screen_filename"]

            sample = {
                "image": [
                    f"{IMAGE_PREFIX}/{app_name}/states/{from_screen}",
                    f"{IMAGE_PREFIX}/{app_name}/states/{to_screen}",
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

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"Input CSV: {INPUT_SPLIT_CSV}")
    print(f"Target split: {TARGET_SPLIT}")
    print(f"Generated samples: {len(dataset)}")
    print(f"Output JSON: {OUTPUT_JSON}")
    print("Mapped action stats:")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    if skipped:
        print("Skipped source action stats:")
        for k in sorted(skipped):
            print(f"  {k}: {skipped[k]}")


if __name__ == "__main__":
    main()
