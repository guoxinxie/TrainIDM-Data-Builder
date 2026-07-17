"""Set-of-Mark agent using the before screenshot and view hierarchy."""

import base64
import importlib.util
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _load_cot_agent_module():
    path = Path(__file__).resolve().with_name("agent-cot.py")
    spec = importlib.util.spec_from_file_location("agent_cot_shared_for_som", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load shared agent helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_cot_agent_module()
AGENT_CONFIG = _BASE.AGENT_CONFIG


SOM_PROMPT = """
You are an expert mobile UI inverse-dynamics agent. You are given three images:
- IMAGE 1: The raw UI state BEFORE an action.
- IMAGE 2: The same BEFORE state with Set-of-Mark boxes and numeric component indexes.
- IMAGE 3: The raw UI state AFTER the action.

Infer the single action on the BEFORE state that caused the transition. For component-targeted actions, select an index that is visible in IMAGE 2 and listed below. All indexes refer to BEFORE-state GUI components.

### BEFORE-STATE GUI COMPONENTS:
{components}

### ACTION SCHEMA:
Choose exactly ONE action:
1. {{"action_type": "click", "index": <integer>}}
2. {{"action_type": "input_text", "index": <integer>, "text": "<text>"}}
3. {{"action_type": "scroll", "direction": "up" | "left" | "right" | "down", "index": <integer>}}
4. {{"action_type": "navigate_back"}}
5. {{"action_type": "long_press", "index": <integer>}}
6. {{"action_type": "wait"}}

For a whole-screen scroll, select the index of the full-screen or scrollable container. "scroll down" means content moves up and lower content becomes visible.

### OUTPUT:
Return exactly one valid JSON object. Do not include reasoning, prose, or Markdown fences.
""".strip()


def _state_json_path(image_path: str) -> Path:
    path = Path(image_path)
    suffix = path.stem[len("screen_") :] if path.stem.startswith("screen_") else path.stem
    return path.with_name(f"state_{suffix}.json")


def _parse_bbox(view):
    raw = view.get("bound_box")
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) == 4 and all(re.fullmatch(r"-?\d+", part) for part in parts):
            x1, y1, x2, y2 = map(int, parts)
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
    return None


def _valid_component(view, bbox, width, height):
    if not bool(view.get("visible", True)):
        return False
    left, top, right, bottom = bbox
    return not (
        left >= right
        or top >= bottom
        or left >= width
        or top >= height
        or right <= 0
        or bottom <= 0
    )


def _component_line(index, view, bbox):
    component = {
        "index": index,
        "bbox": list(bbox),
        "class": view.get("class"),
    }
    for key in ("text", "content_description", "resource_id"):
        if view.get(key) not in (None, ""):
            component[key] = view.get(key)
    for key in (
        "clickable",
        "long_clickable",
        "editable",
        "scrollable",
        "checkable",
        "checked",
        "selected",
    ):
        component[key] = bool(view.get(key))
    return json.dumps(component, ensure_ascii=False, separators=(",", ":"))


def _load_som_font(font_size):
    candidates = (
        "DejaVuSans-Bold.ttf",
        "Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    )
    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


def _rectangles_overlap(first, second, margin=2):
    return not (
        first[2] + margin <= second[0]
        or second[2] + margin <= first[0]
        or first[3] + margin <= second[1]
        or second[3] + margin <= first[1]
    )


def _place_label(anchor_x, anchor_y, label_width, label_height, image, occupied):
    max_x = max(image.width - label_width, 0)
    max_y = max(image.height - label_height, 0)
    step_x = label_width + 3
    step_y = label_height + 3
    seen = set()

    # Search outward from the component's top-left corner. This keeps duplicate
    # and nested component indexes readable instead of drawing them on top of
    # one another.
    for radius in range(0, 13):
        offsets = [(0, 0)] if radius == 0 else []
        for dx in range(-radius, radius + 1):
            offsets.append((dx, -radius))
            offsets.append((dx, radius))
        for dy in range(-radius + 1, radius):
            offsets.append((-radius, dy))
            offsets.append((radius, dy))

        for dx, dy in offsets:
            x = max(0, min(anchor_x + dx * step_x, max_x))
            y = max(0, min(anchor_y + dy * step_y, max_y))
            if (x, y) in seen:
                continue
            seen.add((x, y))
            candidate = (x, y, x + label_width, y + label_height)
            if not any(_rectangles_overlap(candidate, other) for other in occupied):
                return candidate

    # A very dense screen may not have a collision-free nearby slot. Keeping a
    # large badge at the anchor is still more readable than shrinking the font.
    x = max(0, min(anchor_x, max_x))
    y = max(0, min(anchor_y, max_y))
    return x, y, x + label_width, y + label_height


def _draw_som(image, components):
    marked = image.convert("RGB").copy()
    draw = ImageDraw.Draw(marked)
    min_dimension = min(marked.width, marked.height)
    font_size = max(28, min(48, int(round(min_dimension * 0.035))))
    font = _load_som_font(font_size)
    box_width = max(3, min(6, int(round(min_dimension / 300))))
    padding = max(4, font_size // 8)

    clamped_components = {}
    for index, component in components.items():
        left, top, right, bottom = component["bbox"]
        left = max(0, min(left, marked.width - 1))
        right = max(0, min(right, marked.width - 1))
        top = max(0, min(top, marked.height - 1))
        bottom = max(0, min(bottom, marked.height - 1))
        clamped_components[index] = (left, top, right, bottom)
        draw.rectangle(
            (left, top, right, bottom),
            outline=(0, 255, 0),
            width=box_width,
        )

    occupied = []
    for index, (left, top, _right, _bottom) in clamped_components.items():
        label = str(index)
        text_box = draw.textbbox((0, 0), label, font=font, stroke_width=1)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        label_width = text_width + 2 * padding
        label_height = text_height + 2 * padding
        label_box = _place_label(
            left,
            top,
            label_width,
            label_height,
            marked,
            occupied,
        )
        occupied.append(label_box)

        label_left, label_top, label_right, label_bottom = label_box
        if (label_left, label_top) != (left, top):
            draw.line(
                (left, top, label_left + label_width // 2, label_top + label_height // 2),
                fill=(0, 180, 0),
                width=max(2, box_width - 1),
            )
        draw.rectangle(
            label_box,
            fill=(255, 255, 0),
            outline=(0, 0, 0),
            width=2,
        )
        draw.text(
            (
                label_left + padding - text_box[0],
                label_top + padding - text_box[1],
            ),
            label,
            fill=(0, 0, 0),
            font=font,
            stroke_width=1,
            stroke_fill=(0, 0, 0),
        )
    return marked


def _encode_pil_image(image):
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=92)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _build_input(before_state_path: str, after_state_path: str):
    hierarchy_path = _state_json_path(before_state_path)
    if not hierarchy_path.exists():
        raise FileNotFoundError(f"Before-state hierarchy not found: {hierarchy_path}")
    with Image.open(before_state_path) as image:
        before_image = image.convert("RGB")
    with open(hierarchy_path, "r", encoding="utf-8") as hierarchy_file:
        hierarchy = json.load(hierarchy_file)

    components = {}
    component_lines = []
    for index, view in enumerate(hierarchy.get("views", [])):
        bbox = _parse_bbox(view)
        if bbox is None or not _valid_component(
            view, bbox, before_image.width, before_image.height
        ):
            continue
        components[index] = {"bbox": bbox}
        component_lines.append(_component_line(index, view, bbox))
    if not components:
        raise ValueError(f"No valid GUI components in {hierarchy_path}")

    marked_b64 = _encode_pil_image(_draw_som(before_image, components))
    before_b64 = _BASE._encode_image(before_state_path)
    after_b64 = _BASE._encode_image(after_state_path)
    prompt = SOM_PROMPT.format(components="\n".join(component_lines))
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{before_b64}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{marked_b64}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{after_b64}"}},
    ]
    return content, components


def _validate_action(action, components):
    action_type = str(action.get("action_type", "")).strip().lower()
    allowed = {"click", "input_text", "scroll", "navigate_back", "long_press", "wait"}
    if action_type not in allowed:
        return None, f"Unsupported action_type: {action_type or '<missing>'}"
    action["action_type"] = action_type

    index = action.get("index")
    if isinstance(index, str) and re.fullmatch(r"\d+", index.strip()):
        index = int(index.strip())
    if action_type in {"click", "input_text", "long_press", "scroll"}:
        if not isinstance(index, int) or isinstance(index, bool):
            return None, f"{action_type} requires an integer component index"
    if index is not None:
        if not isinstance(index, int) or isinstance(index, bool) or index not in components:
            return None, f"Component index {index} is not in the BEFORE hierarchy"
        action["index"] = index
    if action_type == "input_text" and "text" not in action:
        return None, "input_text requires text"
    if action_type == "scroll":
        direction = str(action.get("direction", "")).strip().lower()
        if direction not in {"up", "down", "left", "right"}:
            return None, "scroll requires a valid direction"
        action["direction"] = direction
        action["index"] = index
    return action, ""


def infer_action_from_state_paths(before_state_path: str, after_state_path: str):
    try:
        content, components = _build_input(before_state_path, after_state_path)
    except Exception as error:
        return {"ok": False, "error": f"SoM input construction failed: {error}"}

    model_result = _BASE._call_remote_model([{"role": "user", "content": content}])
    if not model_result.get("ok"):
        return model_result
    message_content = model_result.get("message_content", "")
    action_obj = _BASE._parse_action_json(message_content)
    if not isinstance(action_obj, dict):
        return {
            "ok": False,
            "error": "Model output does not contain valid action JSON",
            "raw_output": message_content,
        }
    action_obj, error = _validate_action(action_obj, components)
    if action_obj is None:
        return {"ok": False, "error": error, "raw_output": message_content}
    return {
        "ok": True,
        "action": json.dumps(action_obj, ensure_ascii=False),
        "raw_output": message_content,
    }


def remote_vlm_agent(before_state_path: str, after_state_path: str):
    return infer_action_from_state_paths(before_state_path, after_state_path)


AGENT_REGISTRY = {"som": remote_vlm_agent}
