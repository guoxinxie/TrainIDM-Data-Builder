#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate an HTML preview for valid/invalid GUI transition pairs."
    )
    parser.add_argument("--csv", default="filter_mv_trace.csv", help="Input CSV path.")
    parser.add_argument("--root-dir", default="mv_trace_en", help="Dataset root directory.")
    parser.add_argument(
        "--output",
        default="filter_mv_trace_preview.html",
        help="Output HTML path."
    )
    return parser.parse_args()


def parse_valid(value):
    value = str(value or "").strip().lower()
    if value == "true":
        return "valid"
    if value == "false":
        return "invalid"
    return None


def extract_bbox_from_action(action):
    if not isinstance(action, str):
        return None
    match = re.search(
        r"(?:bound_box|bounding_box|bbox)\s*=\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)",
        action,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if left == right or top == bottom:
        return None
    return [left, top, right, bottom]


def resolve_image_path(root_dir, app_name, filename, cache):
    key = (app_name, filename)
    if key in cache:
        return cache[key]

    app_dir = Path(root_dir) / app_name
    candidates = [
        app_dir / "states" / filename,
        app_dir / filename,
    ]
    for path in candidates:
        if path.exists():
            cache[key] = path
            return path

    # Fallback: search inside app dir when structure is different.
    if app_dir.exists():
        for path in app_dir.rglob(filename):
            if path.is_file():
                cache[key] = path
                return path

    cache[key] = None
    return None


def build_data(csv_path, root_dir, output_html):
    data = {"valid": [], "invalid": []}
    image_cache = {}
    output_parent = Path(output_html).resolve().parent

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            category = parse_valid(row.get("valid"))
            if category is None:
                continue

            app_name = row.get("app_name", "")
            from_name = row.get("from_screen_filename", "")
            to_name = row.get("to_screen_filename", "")

            from_path = resolve_image_path(root_dir, app_name, from_name, image_cache)
            to_path = resolve_image_path(root_dir, app_name, to_name, image_cache)

            from_rel = ""
            to_rel = ""
            if from_path is not None:
                from_rel = Path(os.path.relpath(from_path.resolve(), output_parent)).as_posix()
            if to_path is not None:
                to_rel = Path(os.path.relpath(to_path.resolve(), output_parent)).as_posix()

            data[category].append(
                {
                    "id": idx,
                    "app_name": app_name,
                    "action": row.get("action", ""),
                    "screen1_bbox": extract_bbox_from_action(row.get("action", "")),
                    "reason": row.get("reason", ""),
                    "violations": row.get("violations", ""),
                    "from_img": from_rel,
                    "to_img": to_rel,
                    "from_name": from_name,
                    "to_name": to_name,
                }
            )

    return data


def render_html(data):
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GUI Transition Preview</title>
  <style>
    :root {{
      --bg: #f7f8fb;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --accent: #2563eb;
      --border: #e5e7eb;
    }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }}
    .wrap {{ max-width: 1500px; margin: 10px auto; padding: 0 12px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }}
    .row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    button {{ border: 1px solid var(--border); background: #fff; color: var(--text); padding: 8px 12px; border-radius: 8px; cursor: pointer; }}
    button.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .meta {{ margin-top: 10px; font-size: 14px; color: var(--muted); }}
    .details {{ margin-top: 6px; font-size: 14px; line-height: 1.55; }}
    .label {{ color: var(--muted); }}
    .images {{ margin-top: 12px; display: grid; grid-template-columns: minmax(0, 1fr) 360px minmax(0, 1fr); gap: 12px; align-items: start; }}
    .card {{ border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: #fafafa; }}
    .meta-card {{ border: 1px solid var(--border); border-radius: 10px; background: #fff; padding: 12px; }}
    .card h3 {{ margin: 0; padding: 8px 10px; font-size: 14px; border-bottom: 1px solid var(--border); background: #fff; }}
    .image-stage {{ position: relative; width: 100%; height: min(72vh, 820px); background: #f3f4f6; }}
    .card img {{ width: 100%; height: 100%; display: block; object-fit: contain; background: #f3f4f6; }}
    .bbox-overlay {{
      position: absolute;
      border: 3px solid #dc2626;
      background: rgba(220, 38, 38, 0.15);
      pointer-events: none;
      box-sizing: border-box;
    }}
    .action-value {{ font-weight: 700; color: #111827; }}
    .missing {{ padding: 16px; color: #b91c1c; font-size: 13px; }}
    @media (max-width: 900px) {{
      .images {{ grid-template-columns: 1fr; }}
      .image-stage {{ height: min(58vh, 520px); }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <div class="row">
        <button id="btn-valid">Valid</button>
        <button id="btn-invalid">Invalid</button>
      </div>
      <div class="row" style="margin-top:10px;">
        <button id="btn-prev">Last</button>
        <button id="btn-next">Next</button>
        <span id="position" class="meta"></span>
      </div>
      <div id="summary" class="meta"></div>
      <div class="images">
        <div class="card">
          <h3>Screen 1 (Before)</h3>
          <div id="from-wrap"></div>
        </div>
        <div class="meta-card">
          <div class="details">
            <div><span class="label">App:</span> <span id="app-name">-</span></div>
            <div><span class="label">Action:</span> <span id="action" class="action-value">-</span></div>
            <div><span class="label">Violations:</span> <span id="violations">-</span></div>
            <div><span class="label">Reason:</span> <span id="reason">-</span></div>
          </div>
        </div>
        <div class="card">
          <h3>Screen 2 (After)</h3>
          <div id="to-wrap"></div>
        </div>
      </div>
    </div>
  </div>

  <script id="data-json" type="application/json">{data_json}</script>
  <script>
    const DATA = JSON.parse(document.getElementById("data-json").textContent);
    const state = {{
      category: "valid",
      indexByCategory: {{ valid: 0, invalid: 0 }},
    }};

    const el = {{
      btnValid: document.getElementById("btn-valid"),
      btnInvalid: document.getElementById("btn-invalid"),
      btnPrev: document.getElementById("btn-prev"),
      btnNext: document.getElementById("btn-next"),
      summary: document.getElementById("summary"),
      pos: document.getElementById("position"),
      app: document.getElementById("app-name"),
      action: document.getElementById("action"),
      reason: document.getElementById("reason"),
      violations: document.getElementById("violations"),
      fromWrap: document.getElementById("from-wrap"),
      toWrap: document.getElementById("to-wrap"),
    }};

    function currentItems() {{
      return DATA[state.category] || [];
    }}

    function currentIndex() {{
      return state.indexByCategory[state.category] || 0;
    }}

    function setCurrentIndex(nextIdx) {{
      state.indexByCategory[state.category] = nextIdx;
    }}

    function applyBboxOverlay(stage, img, overlay, bbox) {{
      if (!bbox || !Array.isArray(bbox) || bbox.length !== 4) {{
        overlay.style.display = "none";
        return;
      }}
      const [x1, y1, x2, y2] = bbox.map(Number);
      if (![x1, y1, x2, y2].every(Number.isFinite)) {{
        overlay.style.display = "none";
        return;
      }}

      const naturalW = img.naturalWidth;
      const naturalH = img.naturalHeight;
      const stageW = img.clientWidth;
      const stageH = img.clientHeight;
      if (!naturalW || !naturalH || !stageW || !stageH) {{
        overlay.style.display = "none";
        return;
      }}

      const ratio = Math.min(stageW / naturalW, stageH / naturalH);
      const renderedW = naturalW * ratio;
      const renderedH = naturalH * ratio;
      const offsetX = (stageW - renderedW) / 2;
      const offsetY = (stageH - renderedH) / 2;

      const left = Math.max(0, Math.min(x1, x2));
      const right = Math.min(naturalW, Math.max(x1, x2));
      const top = Math.max(0, Math.min(y1, y2));
      const bottom = Math.min(naturalH, Math.max(y1, y2));
      if (left >= right || top >= bottom) {{
        overlay.style.display = "none";
        return;
      }}

      overlay.style.display = "block";
      overlay.style.left = (offsetX + left * ratio) + "px";
      overlay.style.top = (offsetY + top * ratio) + "px";
      overlay.style.width = ((right - left) * ratio) + "px";
      overlay.style.height = ((bottom - top) * ratio) + "px";
    }}

    function renderImage(container, src, fallbackName, bbox) {{
      container.innerHTML = "";
      if (!src) {{
        const div = document.createElement("div");
        div.className = "missing";
        div.textContent = "Image not found: " + (fallbackName || "");
        container.appendChild(div);
        return;
      }}

      const stage = document.createElement("div");
      stage.className = "image-stage";

      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = src;
      img.alt = fallbackName || "screen";
      const overlay = document.createElement("div");
      overlay.className = "bbox-overlay";
      overlay.style.display = "none";

      img.onload = () => applyBboxOverlay(stage, img, overlay, bbox);
      img.onerror = () => {{
        container.innerHTML = '<div class="missing">Failed to load image: ' + (fallbackName || '') + '</div>';
      }};

      stage.appendChild(img);
      stage.appendChild(overlay);
      container.appendChild(stage);
    }}

    function render() {{
      const items = currentItems();
      const total = items.length;
      let idx = currentIndex();
      if (idx < 0) idx = 0;
      if (idx >= total && total > 0) idx = total - 1;
      setCurrentIndex(idx);

      el.btnValid.classList.toggle("active", state.category === "valid");
      el.btnInvalid.classList.toggle("active", state.category === "invalid");
      el.summary.textContent = `Valid: ${{DATA.valid.length}} | Invalid: ${{DATA.invalid.length}}`;

      if (total === 0) {{
        el.pos.textContent = `0 / 0 (${{state.category}})`;
        el.btnPrev.disabled = true;
        el.btnNext.disabled = true;
        el.app.textContent = "-";
        el.action.textContent = "-";
        el.reason.textContent = "-";
        el.violations.textContent = "-";
        renderImage(el.fromWrap, "", "");
        renderImage(el.toWrap, "", "");
        return;
      }}

      const item = items[idx];
      el.pos.textContent = `${{idx + 1}} / ${{total}} (${{state.category}})`;
      el.btnPrev.disabled = idx <= 0;
      el.btnNext.disabled = idx >= total - 1;
      el.app.textContent = item.app_name || "-";
      el.action.textContent = item.action || "-";
      el.reason.textContent = item.reason || "-";
      el.violations.textContent = item.violations || "[]";

      renderImage(el.fromWrap, item.from_img, item.from_name, item.screen1_bbox);
      renderImage(el.toWrap, item.to_img, item.to_name, null);
    }}

    el.btnValid.onclick = () => {{ state.category = "valid"; render(); }};
    el.btnInvalid.onclick = () => {{ state.category = "invalid"; render(); }};
    el.btnPrev.onclick = () => {{ setCurrentIndex(currentIndex() - 1); render(); }};
    el.btnNext.onclick = () => {{ setCurrentIndex(currentIndex() + 1); render(); }};
    document.addEventListener("keydown", (e) => {{
      if (e.key === "ArrowLeft") el.btnPrev.click();
      if (e.key === "ArrowRight") el.btnNext.click();
    }});

    render();
  </script>
</body>
</html>
"""


def main():
    args = parse_args()
    data = build_data(args.csv, args.root_dir, args.output)
    output_path = Path(args.output)
    output_path.write_text(render_html(data), encoding="utf-8")
    print(
        f"Generated {output_path} | valid={len(data['valid'])} | invalid={len(data['invalid'])}"
    )


if __name__ == "__main__":
    main()
