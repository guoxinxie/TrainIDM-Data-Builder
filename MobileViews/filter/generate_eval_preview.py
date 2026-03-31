#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate HTML preview for eval_comparison_outputs.csv with GT/pred overlays."
    )
    parser.add_argument("--csv", default="eval_comparison_outputs.csv", help="Input eval CSV path.")
    parser.add_argument("--output", default="eval_comparison_preview.html", help="Output HTML path.")
    return parser.parse_args()


def parse_bool(value):
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def extract_bbox_from_gt_action(action_text):
    if not isinstance(action_text, str):
        return None
    m = re.search(
        r"(?:bound_box|bounding_box|bbox)\s*=\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)",
        action_text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if left == right or top == bottom:
        return None
    return [left, top, right, bottom]


def parse_predicted_action(predicted_action_text):
    result = {
        "type": "",
        "point": None,
        "direction": "",
    }

    text = str(predicted_action_text or "").strip()
    if not text:
        return result

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        obj = json.loads(text)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return result
        try:
            obj = json.loads(match.group(0))
        except Exception:
            return result

    if not isinstance(obj, dict):
        return result

    action_type = str(obj.get("action_type", "")).strip().lower()
    result["type"] = action_type

    if action_type in {"click", "long_press"}:
        x = obj.get("x")
        y = obj.get("y")
        if isinstance(x, int) and isinstance(y, int):
            result["point"] = [x, y]
        elif isinstance(x, list) and len(x) == 2 and isinstance(x[0], int) and isinstance(x[1], int):
            # Supports format like {"action_type":"click","x":[497,579]}
            result["point"] = [x[0], x[1]]

    if action_type == "scroll":
        direction = str(obj.get("direction", "")).strip().lower()
        result["direction"] = direction

    return result


def resolve_image_path(path_str, output_parent):
    if not path_str:
        return ""

    p = Path(path_str)
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()

    if not p.exists():
        return ""

    return Path(os.path.relpath(p, output_parent)).as_posix()


def build_data(csv_path, output_html):
    data = {"matched": [], "mismatched": [], "error": []}
    output_parent = Path(output_html).resolve().parent

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            exact_action_match = parse_bool(row.get("exact_action_match"))
            agent_ok = parse_bool(row.get("agent_ok"))

            if agent_ok is False:
                category = "error"
            elif exact_action_match is True:
                category = "matched"
            else:
                category = "mismatched"

            from_rel = resolve_image_path(row.get("before_state_path", ""), output_parent)
            to_rel = resolve_image_path(row.get("after_state_path", ""), output_parent)

            pred = parse_predicted_action(row.get("predicted_action", ""))

            data[category].append(
                {
                    "id": idx,
                    "app_name": row.get("app_name", ""),
                    "ground_truth_action": row.get("ground_truth_action", ""),
                    "ground_truth_action_type": row.get("ground_truth_action_type", ""),
                    "predicted_action": row.get("predicted_action", ""),
                    "predicted_action_type": row.get("predicted_action_type", ""),
                    "action_type_match": row.get("action_type_match", ""),
                    "exact_action_match": row.get("exact_action_match", ""),
                    "agent_ok": row.get("agent_ok", ""),
                    "agent_error": row.get("agent_error", ""),
                    "gt_bbox": extract_bbox_from_gt_action(row.get("ground_truth_action", "")),
                    "pred_point": pred["point"],
                    "pred_type": pred["type"],
                    "pred_direction": pred["direction"],
                    "from_img": from_rel,
                    "to_img": to_rel,
                    "from_name": os.path.basename(row.get("before_state_path", "")),
                    "to_name": os.path.basename(row.get("after_state_path", "")),
                }
            )

    return data


def render_html(data):
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Eval Action Preview</title>
  <style>
    :root {{
      --bg: #f7f8fb;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --accent: #2563eb;
      --border: #e5e7eb;
      --gt: #dc2626;
      --pred: #2563eb;
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
    .images {{ margin-top: 12px; display: grid; grid-template-columns: minmax(0, 1fr) 380px minmax(0, 1fr); gap: 12px; align-items: start; }}
    .card {{ border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: #fafafa; }}
    .meta-card {{ border: 1px solid var(--border); border-radius: 10px; background: #fff; padding: 12px; }}
    .card h3 {{ margin: 0; padding: 8px 10px; font-size: 14px; border-bottom: 1px solid var(--border); background: #fff; }}
    .image-stage {{ position: relative; width: 100%; height: min(72vh, 820px); background: #f3f4f6; }}
    .card img {{ width: 100%; height: 100%; display: block; object-fit: contain; background: #f3f4f6; }}
    .gt-bbox-overlay {{
      position: absolute;
      border: 3px solid var(--gt);
      background: rgba(220, 38, 38, 0.16);
      pointer-events: none;
      box-sizing: border-box;
      display: none;
    }}
    .pred-point-overlay {{
      position: absolute;
      width: 14px;
      height: 14px;
      border: 3px solid #ffffff;
      outline: 3px solid var(--pred);
      border-radius: 999px;
      background: var(--pred);
      pointer-events: none;
      box-sizing: border-box;
      transform: translate(-50%, -50%);
      display: none;
    }}
    .pred-tag {{
      position: absolute;
      top: 10px;
      right: 10px;
      background: rgba(37, 99, 235, 0.9);
      color: #fff;
      border-radius: 6px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 600;
      display: none;
    }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 700; margin-left: 6px; }}
    .badge-ok {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
    .badge-bad {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}
    .legend {{ margin-top: 8px; font-size: 12px; color: var(--muted); }}
    .legend-dot {{ display:inline-block; width:10px; height:10px; border-radius:999px; margin-right:4px; vertical-align:middle; }}
    .legend-box {{ display:inline-block; width:14px; height:10px; margin-right:4px; vertical-align:middle; border:2px solid var(--gt); background: rgba(220,38,38,.16); }}
    .action-value {{ font-weight: 700; color: #111827; word-break: break-word; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; word-break: break-all; }}
    .missing {{ padding: 16px; color: #b91c1c; font-size: 13px; }}
    @media (max-width: 900px) {{
      .images {{ grid-template-columns: 1fr; }}
      .image-stage {{ height: min(58vh, 520px); }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"panel\">
      <div class=\"row\">
        <button id=\"btn-matched\">Matched</button>
        <button id=\"btn-mismatched\">Mismatched</button>
        <button id=\"btn-error\">Error</button>
      </div>
      <div class=\"row\" style=\"margin-top:10px;\">
        <button id=\"btn-prev\">Last</button>
        <button id=\"btn-next\">Next</button>
        <span id=\"position\" class=\"meta\"></span>
      </div>
      <div id=\"summary\" class=\"meta\"></div>
      <div class=\"images\">
        <div class=\"card\">
          <h3>Screen 1 (Before) - GT + Pred Overlay</h3>
          <div id=\"from-wrap\"></div>
        </div>
        <div class=\"meta-card\">
          <div class=\"details\">
            <div><span class=\"label\">App:</span> <span id=\"app-name\">-</span></div>
            <div><span class=\"label\">Type Match:</span> <span id=\"type-match\">-</span></div>
            <div><span class=\"label\">Exact Match:</span> <span id=\"exact-match\">-</span></div>
            <div><span class=\"label\">GT Action:</span> <span id=\"gt-action\" class=\"action-value\">-</span></div>
            <div><span class=\"label\">Pred Action:</span> <span id=\"pred-action\" class=\"action-value\">-</span></div>
            <div><span class=\"label\">Agent Error:</span> <span id=\"agent-error\" class=\"mono\">-</span></div>
            <div class=\"legend\">
              <span class=\"legend-box\"></span>Ground Truth BBox
              <span style=\"margin-left:10px;\"><span class=\"legend-dot\" style=\"background:#2563eb;\"></span>Predicted Click/LongPress Point</span>
            </div>
          </div>
        </div>
        <div class=\"card\">
          <h3>Screen 2 (After)</h3>
          <div id=\"to-wrap\"></div>
        </div>
      </div>
    </div>
  </div>

  <script id=\"data-json\" type=\"application/json\">{data_json}</script>
  <script>
    const DATA = JSON.parse(document.getElementById("data-json").textContent);
    const state = {{ category: "matched", idx: {{ matched: 0, mismatched: 0, error: 0 }} }};

    const el = {{
      btnMatched: document.getElementById("btn-matched"),
      btnMismatched: document.getElementById("btn-mismatched"),
      btnError: document.getElementById("btn-error"),
      btnPrev: document.getElementById("btn-prev"),
      btnNext: document.getElementById("btn-next"),
      summary: document.getElementById("summary"),
      pos: document.getElementById("position"),
      app: document.getElementById("app-name"),
      gtAction: document.getElementById("gt-action"),
      predAction: document.getElementById("pred-action"),
      typeMatch: document.getElementById("type-match"),
      exactMatch: document.getElementById("exact-match"),
      agentError: document.getElementById("agent-error"),
      fromWrap: document.getElementById("from-wrap"),
      toWrap: document.getElementById("to-wrap"),
    }};

    function currentItems() {{ return DATA[state.category] || []; }}
    function currentIndex() {{ return state.idx[state.category] || 0; }}
    function setCurrentIndex(i) {{ state.idx[state.category] = i; }}

    function boolBadge(value) {{
      const text = String(value || "").trim().toLowerCase();
      if (text === "true") return '<span class="badge badge-ok">TRUE</span>';
      if (text === "false") return '<span class="badge badge-bad">FALSE</span>';
      return '<span class="badge">-</span>';
    }}

    function applyBbox(stage, img, overlay, bbox) {{
      if (!bbox || !Array.isArray(bbox) || bbox.length !== 4) {{ overlay.style.display = "none"; return; }}
      const [x1, y1, x2, y2] = bbox.map(Number);
      if (![x1,y1,x2,y2].every(Number.isFinite)) {{ overlay.style.display = "none"; return; }}

      const naturalW = img.naturalWidth, naturalH = img.naturalHeight;
      const stageW = img.clientWidth, stageH = img.clientHeight;
      if (!naturalW || !naturalH || !stageW || !stageH) {{ overlay.style.display = "none"; return; }}

      const ratio = Math.min(stageW / naturalW, stageH / naturalH);
      const renderedW = naturalW * ratio;
      const renderedH = naturalH * ratio;
      const offsetX = (stageW - renderedW) / 2;
      const offsetY = (stageH - renderedH) / 2;

      const left = Math.max(0, Math.min(x1, x2));
      const right = Math.min(naturalW, Math.max(x1, x2));
      const top = Math.max(0, Math.min(y1, y2));
      const bottom = Math.min(naturalH, Math.max(y1, y2));
      if (left >= right || top >= bottom) {{ overlay.style.display = "none"; return; }}

      overlay.style.display = "block";
      overlay.style.left = (offsetX + left * ratio) + "px";
      overlay.style.top = (offsetY + top * ratio) + "px";
      overlay.style.width = ((right - left) * ratio) + "px";
      overlay.style.height = ((bottom - top) * ratio) + "px";
    }}

    function applyPoint(stage, img, pointEl, point) {{
      if (!point || !Array.isArray(point) || point.length !== 2) {{ pointEl.style.display = "none"; return; }}
      const [x, y] = point.map(Number);
      if (![x,y].every(Number.isFinite)) {{ pointEl.style.display = "none"; return; }}

      const naturalW = img.naturalWidth, naturalH = img.naturalHeight;
      const stageW = img.clientWidth, stageH = img.clientHeight;
      if (!naturalW || !naturalH || !stageW || !stageH) {{ pointEl.style.display = "none"; return; }}

      const ratio = Math.min(stageW / naturalW, stageH / naturalH);
      const renderedW = naturalW * ratio;
      const renderedH = naturalH * ratio;
      const offsetX = (stageW - renderedW) / 2;
      const offsetY = (stageH - renderedH) / 2;

      if (x < 0 || y < 0 || x > naturalW || y > naturalH) {{ pointEl.style.display = "none"; return; }}

      pointEl.style.display = "block";
      pointEl.style.left = (offsetX + x * ratio) + "px";
      pointEl.style.top = (offsetY + y * ratio) + "px";
    }}

    function renderImageWithOverlays(container, src, fallbackName, gtBbox, predPoint, predType, predDirection) {{
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

      const gtOverlay = document.createElement("div");
      gtOverlay.className = "gt-bbox-overlay";

      const predPointEl = document.createElement("div");
      predPointEl.className = "pred-point-overlay";

      const predTag = document.createElement("div");
      predTag.className = "pred-tag";
      if (predType === "scroll" && predDirection) {{
        predTag.style.display = "block";
        predTag.textContent = `pred: scroll ${{predDirection}}`;
      }} else if (predType && predType !== "click" && predType !== "long_press") {{
        predTag.style.display = "block";
        predTag.textContent = `pred: ${{predType}}`;
      }}

      img.onload = () => {{
        applyBbox(stage, img, gtOverlay, gtBbox);
        applyPoint(stage, img, predPointEl, predPoint);
      }};

      img.onerror = () => {{
        container.innerHTML = '<div class="missing">Failed to load image: ' + (fallbackName || '') + '</div>';
      }};

      stage.appendChild(img);
      stage.appendChild(gtOverlay);
      stage.appendChild(predPointEl);
      stage.appendChild(predTag);
      container.appendChild(stage);
    }}

    function renderImageSimple(container, src, fallbackName) {{
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
      img.onerror = () => {{ container.innerHTML = '<div class="missing">Failed to load image: ' + (fallbackName || '') + '</div>'; }};
      stage.appendChild(img);
      container.appendChild(stage);
    }}

    function render() {{
      const items = currentItems();
      const total = items.length;
      let idx = currentIndex();
      if (idx < 0) idx = 0;
      if (idx >= total && total > 0) idx = total - 1;
      setCurrentIndex(idx);

      el.btnMatched.classList.toggle("active", state.category === "matched");
      el.btnMismatched.classList.toggle("active", state.category === "mismatched");
      el.btnError.classList.toggle("active", state.category === "error");
      el.summary.textContent = `Matched: ${{DATA.matched.length}} | Mismatched: ${{DATA.mismatched.length}} | Error: ${{DATA.error.length}}`;

      if (total === 0) {{
        el.pos.textContent = `0 / 0 (${{state.category}})`;
        el.btnPrev.disabled = true;
        el.btnNext.disabled = true;
        el.app.textContent = "-";
        el.gtAction.textContent = "-";
        el.predAction.textContent = "-";
        el.typeMatch.innerHTML = boolBadge("");
        el.exactMatch.innerHTML = boolBadge("");
        el.agentError.textContent = "-";
        renderImageWithOverlays(el.fromWrap, "", "", null, null, "", "");
        renderImageSimple(el.toWrap, "", "");
        return;
      }}

      const item = items[idx];
      el.pos.textContent = `${{idx + 1}} / ${{total}} (${{state.category}})`;
      el.btnPrev.disabled = idx <= 0;
      el.btnNext.disabled = idx >= total - 1;

      el.app.textContent = item.app_name || "-";
      el.gtAction.textContent = item.ground_truth_action || "-";
      el.predAction.textContent = item.predicted_action || "-";
      el.typeMatch.innerHTML = boolBadge(item.action_type_match);
      el.exactMatch.innerHTML = boolBadge(item.exact_action_match);
      el.agentError.textContent = item.agent_error || "";

      renderImageWithOverlays(
        el.fromWrap,
        item.from_img,
        item.from_name,
        item.gt_bbox,
        item.pred_point,
        item.pred_type,
        item.pred_direction
      );
      renderImageSimple(el.toWrap, item.to_img, item.to_name);
    }}

    el.btnMatched.onclick = () => {{ state.category = "matched"; render(); }};
    el.btnMismatched.onclick = () => {{ state.category = "mismatched"; render(); }};
    el.btnError.onclick = () => {{ state.category = "error"; render(); }};
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
    data = build_data(args.csv, args.output)
    out = Path(args.output)
    out.write_text(render_html(data), encoding="utf-8")
    print(
        f"Generated {out} | matched={len(data['matched'])} | mismatched={len(data['mismatched'])} | error={len(data['error'])}"
    )


if __name__ == "__main__":
    main()
