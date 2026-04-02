import csv
import re
import shutil
from collections import defaultdict
from pathlib import Path

# ================= Config =================
SPLIT_CSV = Path("filtered_metadata/split.csv")
SOURCE_TRACE_ROOT = Path("mv_trace_en")
OUTPUT_ROOT = Path("test_subset")
OUTPUT_TRACE_ROOT = OUTPUT_ROOT / "mv_trace_en"
OUTPUT_TEST_CSV = OUTPUT_ROOT / "split_test.csv"
OUTPUT_SUMMARY = OUTPUT_ROOT / "extract_test_subset_summary.txt"
REQUIRE_VALID_TRUE = True


def is_true(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def copy_one_file(src: Path, dst: Path):
    if not src.exists() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def extract_screen_index(screen_filename: str):
    # Example: screen_123.jpg -> "123"
    match = re.match(r"^screen_(\d+)\.[^.]+$", str(screen_filename or "").strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def resolve_source_file(app_name: str, filename: str):
    candidates = [
        SOURCE_TRACE_ROOT / app_name / "states" / filename,
        SOURCE_TRACE_ROOT / app_name / filename,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def main():
    if not SPLIT_CSV.exists():
        raise FileNotFoundError(f"Missing split CSV: {SPLIT_CSV}")
    if not SOURCE_TRACE_ROOT.exists():
        raise FileNotFoundError(f"Missing source trace root: {SOURCE_TRACE_ROOT}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_TRACE_ROOT.mkdir(parents=True, exist_ok=True)

    with open(SPLIT_CSV, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        if "app_name" not in fieldnames:
            raise ValueError("split.csv must contain 'app_name'.")
        if "from_screen_filename" not in fieldnames:
            raise ValueError("split.csv must contain 'from_screen_filename'.")
        if "to_screen_filename" not in fieldnames:
            raise ValueError("split.csv must contain 'to_screen_filename'.")
        if "split" not in fieldnames:
            raise ValueError("split.csv must contain 'split'.")
        if REQUIRE_VALID_TRUE and "valid" not in fieldnames:
            raise ValueError("split.csv must contain 'valid' when REQUIRE_VALID_TRUE=True.")

        test_rows = []
        needed_images_by_app = defaultdict(set)
        for row in reader:
            if str(row.get("split", "")).strip().lower() != "test":
                continue
            if REQUIRE_VALID_TRUE and not is_true(row.get("valid")):
                continue

            app_name = str(row.get("app_name", "")).strip()
            before_img = str(row.get("from_screen_filename", "")).strip()
            after_img = str(row.get("to_screen_filename", "")).strip()
            if not app_name or not before_img or not after_img:
                continue

            test_rows.append(row)
            needed_images_by_app[app_name].add(before_img)
            needed_images_by_app[app_name].add(after_img)

    if not test_rows:
        raise ValueError("No test rows found in split.csv under current filters.")

    with open(OUTPUT_TEST_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(test_rows)

    total_needed_files = 0
    copied_files = 0
    missing_files = []
    artifact_needed = defaultdict(int)
    artifact_copied = defaultdict(int)
    artifact_missing = defaultdict(int)

    for app_name in sorted(needed_images_by_app):
        app_images = sorted(needed_images_by_app[app_name])
        for image_name in app_images:
            screen_idx = extract_screen_index(image_name)
            targets = [("screen", image_name)]
            if screen_idx is not None:
                targets.append(("state", f"state_{screen_idx}.json"))
                targets.append(("window_dump", f"window_dump_{screen_idx}.xml"))

            for artifact_type, filename in targets:
                total_needed_files += 1
                artifact_needed[artifact_type] += 1

                src_path = resolve_source_file(app_name, filename)
                dst_path = OUTPUT_TRACE_ROOT / app_name / "states" / filename

                if src_path is None:
                    missing_files.append(f"{app_name}/states/{filename}")
                    artifact_missing[artifact_type] += 1
                    continue

                ok = copy_one_file(src_path, dst_path)
                if ok:
                    copied_files += 1
                    artifact_copied[artifact_type] += 1
                else:
                    missing_files.append(f"{app_name}/states/{filename}")
                    artifact_missing[artifact_type] += 1

    summary_lines = [
        "extract_test_subset_summary",
        f"split_csv: {SPLIT_CSV}",
        f"source_trace_root: {SOURCE_TRACE_ROOT}",
        f"output_root: {OUTPUT_ROOT}",
        f"output_trace_root: {OUTPUT_TRACE_ROOT}",
        f"output_test_csv: {OUTPUT_TEST_CSV}",
        f"require_valid_true: {REQUIRE_VALID_TRUE}",
        f"test_rows: {len(test_rows)}",
        f"test_apps: {len(needed_images_by_app)}",
        f"needed_files: {total_needed_files}",
        f"copied_files: {copied_files}",
        f"missing_files: {len(missing_files)}",
        "",
    ]

    summary_lines.append("[artifact_stats]")
    for artifact_type in ("screen", "state", "window_dump"):
        summary_lines.append(
            f"{artifact_type}: needed={artifact_needed[artifact_type]}, "
            f"copied={artifact_copied[artifact_type]}, "
            f"missing={artifact_missing[artifact_type]}"
        )
    summary_lines.append("")

    if missing_files:
        summary_lines.append("[missing_file_paths]")
        summary_lines.extend(sorted(missing_files))
        summary_lines.append("")

    with open(OUTPUT_SUMMARY, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))

    print(f"Saved: {OUTPUT_TEST_CSV}")
    print(f"Saved: {OUTPUT_SUMMARY}")
    print(f"Copied files: {copied_files}/{total_needed_files}")
    if missing_files:
        print(f"Missing files: {len(missing_files)}")


if __name__ == "__main__":
    main()
