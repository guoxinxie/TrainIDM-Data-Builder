import csv
import random
import re
from collections import defaultdict
from pathlib import Path

# ================= Config =================
INPUT_DIR = Path("filtered_metadata")
OUTPUT_CSV = INPUT_DIR / "split.csv"
SPLIT_SUMMARIZATION_FILE = INPUT_DIR / "split_summarization.txt"
TRAIN_RATIO = 0.8
SEED = int("91010")


def is_true(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def parse_action_type(action_text):
    text = str(action_text or "").strip().lower()
    if not text:
        return "unknown"
    match = re.match(r"^([a-z_]+)", text)
    if not match:
        return "unknown"
    return match.group(1)


def main():
    if not 0 < TRAIN_RATIO < 1:
        raise ValueError("TRAIN_RATIO must be between 0 and 1.")

    csv_paths = sorted(INPUT_DIR.glob("*.csv"))
    if not csv_paths:
        raise ValueError(f"No CSV files found under {INPUT_DIR}.")

    fieldnames = None
    valid_rows = []
    seen_valid_rows = set()
    total_input_rows = 0
    duplicate_valid_rows = 0

    for csv_path in csv_paths:
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            current_fieldnames = reader.fieldnames or []
            if fieldnames is None:
                fieldnames = current_fieldnames
            elif current_fieldnames != fieldnames:
                raise ValueError(
                    f"Header mismatch in {csv_path}. Expected {fieldnames}, got {current_fieldnames}."
                )

            for row in reader:
                total_input_rows += 1
                if not is_true(row.get("valid")):
                    continue
                row_key = tuple(row.get(col, "") for col in fieldnames)
                if row_key in seen_valid_rows:
                    duplicate_valid_rows += 1
                    continue
                seen_valid_rows.add(row_key)
                valid_rows.append(row)

    fieldnames = fieldnames or []
    if "app_name" not in fieldnames:
        raise ValueError("Input CSV must contain 'app_name' column.")
    if "valid" not in fieldnames:
        raise ValueError("Input CSV must contain 'valid' column.")

    if not valid_rows:
        raise ValueError("No valid rows found across CSV files.")

    rows_by_app = defaultdict(list)
    action_type_stats = defaultdict(int)
    for row in valid_rows:
        app_name = row["app_name"].strip()
        if not app_name:
            raise ValueError("Found a valid row with empty app_name.")
        rows_by_app[app_name].append(row)
        action_type = parse_action_type(row.get("action", ""))
        action_type_stats[action_type] += 1

    apps = sorted(rows_by_app.keys())
    rng = random.Random(SEED)
    rng.shuffle(apps)

    train_app_count = int(len(apps) * TRAIN_RATIO)
    if len(apps) == 1:
        train_app_count = 1
    elif train_app_count <= 0:
        train_app_count = 1
    elif train_app_count >= len(apps):
        train_app_count = len(apps) - 1

    train_apps = set(apps[:train_app_count])
    test_apps = set(apps[train_app_count:])

    split_fieldnames = fieldnames + ["split"]
    for row in valid_rows:
        row["split"] = "train" if row["app_name"] in train_apps else "test"

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=split_fieldnames)
        writer.writeheader()
        writer.writerows(valid_rows)

    train_samples = sum(1 for row in valid_rows if row["split"] == "train")
    test_samples = len(valid_rows) - train_samples
    train_apps_sorted = sorted(train_apps)
    test_apps_sorted = sorted(test_apps)

    lines = [
        "split_summarization",
        f"input_dir: {INPUT_DIR}",
        f"input_csv_count: {len(csv_paths)}",
        f"total_input_rows: {total_input_rows}",
        f"duplicate_valid_rows_skipped: {duplicate_valid_rows}",
        f"output_csv: {OUTPUT_CSV}",
        f"train_ratio: {TRAIN_RATIO}",
        f"random_seed: {SEED}",
        f"total_valid_samples: {len(valid_rows)}",
        f"total_apps: {len(apps)}",
        f"train_app_count: {len(train_apps)}",
        f"test_app_count: {len(test_apps)}",
        f"train_sample_count: {train_samples}",
        f"test_sample_count: {test_samples}",
        "",
        "[train_apps]",
    ]
    lines.extend(train_apps_sorted)
    lines.append("")
    lines.append("[test_apps]")
    lines.extend(test_apps_sorted)
    lines.append("")
    lines.append("[valid_action_type_stats]")
    for action_type in sorted(action_type_stats):
        lines.append(f"{action_type}: {action_type_stats[action_type]}")
    lines.append("")

    with open(SPLIT_SUMMARIZATION_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Total valid samples: {len(valid_rows)}")
    print(f"Total apps: {len(apps)}")
    print(f"Train apps: {len(train_apps)}, Test apps: {len(test_apps)}")
    print(f"Train samples: {train_samples}, Test samples: {test_samples}")
    print(f"Seed: {SEED}")
    print("Valid action type stats:")
    for action_type in sorted(action_type_stats):
        print(f"  {action_type}: {action_type_stats[action_type]}")
    print(f"Saved: {OUTPUT_CSV}")
    print(f"Saved: {SPLIT_SUMMARIZATION_FILE}")


if __name__ == "__main__":
    main()
