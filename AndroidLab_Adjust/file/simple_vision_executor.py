import time
import xml.etree.ElementTree as ET

from page_executor.text_executor import TextOnlyExecutor


class AndroidElement:
    def __init__(self, uid, bbox, attrib):
        self.uid = uid
        self.bbox = bbox
        self.attrib = attrib


def get_id_from_element(elem):
    bounds = elem.attrib["bounds"][1:-1].split("][")
    x1, y1 = map(int, bounds[0].split(","))
    x2, y2 = map(int, bounds[1].split(","))
    elem_w, elem_h = x2 - x1, y2 - y1
    if "resource-id" in elem.attrib and elem.attrib["resource-id"]:
        elem_id = elem.attrib["resource-id"].replace(":", ".").replace("/", "_")
    else:
        elem_id = f"{elem.attrib['class']}_{elem_w}_{elem_h}"
    if "content-desc" in elem.attrib and elem.attrib["content-desc"] and len(elem.attrib["content-desc"]) < 20:
        content_desc = elem.attrib['content-desc'].replace("/", "_").replace(" ", "").replace(":", "_")
        elem_id += f"_{content_desc}"
    return elem_id


def traverse_tree(xml_path, elem_list, attrib, add_index=False):
    path = []
    for event, elem in ET.iterparse(xml_path, ['start', 'end']):
        if event == 'start':
            path.append(elem)
            if attrib in elem.attrib:
                if elem.attrib[attrib] != "true":
                    if elem.attrib["text"].strip() == "" and elem.attrib["content-desc"].strip() == "":
                        continue
                parent_prefix = ""
                if len(path) > 1:
                    parent_prefix = get_id_from_element(path[-2])
                bounds = elem.attrib["bounds"][1:-1].split("][")
                x1, y1 = map(int, bounds[0].split(","))
                x2, y2 = map(int, bounds[1].split(","))
                center = (x1 + x2) // 2, (y1 + y2) // 2
                elem_id = get_id_from_element(elem)
                if parent_prefix:
                    elem_id = parent_prefix + "_" + elem_id
                if add_index:
                    elem_id += f"_{elem.attrib['index']}"
                close = False
                for e in elem_list:
                    bbox = e.bbox
                    center_ = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
                    dist = (abs(center[0] - center_[0]) ** 2 + abs(center[1] - center_[1]) ** 2) ** 0.5
                    if dist <= 5:
                        close = True
                        break
                if not close:
                    elem_list.append(AndroidElement(elem_id, ((x1, y1), (x2, y2)), attrib))

        if event == 'end':
            path.pop()


class VisionExecutor(TextOnlyExecutor):
    def __init__(self, controller, config):
        self.controller = controller
        self.device = controller.device
        self.screenshot_dir = config.screenshot_dir
        self.task_id = int(time.time())

        self.new_page_captured = False
        self.current_screenshot = None
        self.current_return = None
        super().__init__(controller, config)

        self.last_turn_element = None
        self.last_turn_element_tagname = None
        self.is_finish = False
        self.device_pixel_ratio = None
        self.latest_xml = None
        self.elem_list = []
        # self.glm4_key = config.glm4_key

        # self.device_pixel_ratio = self.page.evaluate("window.devicePixelRatio")

    def set_elem_list(self, xml_path):
        clickable_list = []
        focusable_list = []
        traverse_tree(xml_path, clickable_list, "clickable", True)
        traverse_tree(xml_path, focusable_list, "focusable", True)
        elem_list = []
        for elem in clickable_list:
            elem_list.append(elem)
        for elem in focusable_list:
            bbox = elem.bbox
            center = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
            close = False
            for e in clickable_list:
                bbox = e.bbox
                center_ = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
                dist = (abs(center[0] - center_[0]) ** 2 + abs(center[1] - center_[1]) ** 2) ** 0.5
                if dist <= 10:  # configs["MIN_DIST"]
                    close = True
                    break
            if not close:
                elem_list.append(elem)
        self.elem_list = elem_list

    def tap(self, index=None, element=None, start_box=None, **kwargs):
        """
        重写的 tap 方法。
        兼容：模型输出 tap(index) / click(start_box=...) / 框架回退 do(action='Tap', element=[x,y])
        """
        if index is not None:
            if not (0 < index <= len(self.elem_list)):
                print(f"[WARN] Tap index {index} out of range [1, {len(self.elem_list)}]. Waiting.")
                self.wait()
                return

            tl, br = self.elem_list[index - 1].bbox
            x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
            self.controller.tap(x, y)
            self.current_return = {"operation": "do", "action": 'Tap', "kwargs": {"element": (x, y), "index": index}}
        else:
            # 将 element, start_box 及其他参数转交给父类 TextOnlyExecutor 处理
            super().tap(element=element, start_box=start_box, **kwargs)

    def long_press(self, index=None, element=None, start_box=None, **kwargs):
        """
        重写的 long_press 方法。与 tap 逻辑完全一致。
        """
        if index is not None:
            if not (0 < index <= len(self.elem_list)):
                print(f"[WARN] Long press index {index} out of range. Waiting.")
                self.wait()
                return

            tl, br = self.elem_list[index - 1].bbox
            x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
            self.controller.long_press(x, y)
            self.current_return = {"operation": "do", "action": 'Long Press', "kwargs": {"element": (x, y), "index": index}}
        else:
            super().long_press(element=element, start_box=start_box, **kwargs)

    def swipe(self, index=None, direction=None, dist="medium", element=None, **kwargs):
        """
        重写的 swipe 方法。
        兼容：带索引的局部滑动 (index, direction) / 框架回退的全屏滑动 (direction, dist)
        """
        if index is not None:
            if not (0 < index <= len(self.elem_list)):
                print(f"[WARN] Swipe index {index} out of range. Waiting.")
                self.wait()
                return

            tl, br = self.elem_list[index - 1].bbox
            x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
            self.controller.swipe(x, y, direction, dist)
            self.current_return = {"operation": "do", "action": 'Swipe',
                                   "kwargs": {"element": (x, y), "index": index, "direction": direction, "dist": dist}}
        else:
            # 父类如果发现 element=None，会自动从屏幕正中心滑动
            super().swipe(element=element, direction=direction, dist=dist, **kwargs)

    def type(self, input_str=None, text=None, **kwargs):
        """
        输入文本。
        兼容：模型输出 type(input_str="abc") / 框架回退 do(action='Type', text="abc")
        """
        # 优先取 input_str，没有就取 text，再没有就为空
        actual_text = input_str if input_str is not None else text
        if actual_text is None:
            actual_text = kwargs.get("argument", "")  # 终极兜底

        self.controller.text(actual_text)
        self.current_return = {"operation": "do", "action": 'Type', "kwargs": {"text": actual_text}}

    def text(self, input_str=None, text=None, **kwargs):
        """
        作为 type 的别名，防止模型直接调用 text()
        """
        self.type(input_str=input_str, text=text, **kwargs)

    def launch(self, app_name=None, app=None, **kwargs):
        """
        启动 APP。
        兼容：模型输出 launch(app_name="abc") / 框架回退 do(action='Launch', app="abc")
        """
        actual_app = app_name if app_name is not None else app
        if actual_app is None:
            actual_app = kwargs.get("argument", "")

        self.controller.launch(actual_app)
        self.current_return = {"operation": "do", "action": 'Launch', "kwargs": {"app_name": actual_app}}

    # ========================================================
    # 基础控制命令：全部添加 **kwargs 防止 TypeError 崩溃
    # ========================================================

    def back(self, **kwargs):
        self.controller.back()
        self.current_return = {"operation": "do", "action": 'Back', "kwargs": {}}

    def home(self, **kwargs):
        self.controller.home()
        self.current_return = {"operation": "do", "action": 'Home', "kwargs": {}}

    def enter(self, **kwargs):
        self.controller.enter()
        self.current_return = {"operation": "do", "action": 'Enter', "kwargs": {}}

    def wait(self, interval=5, **kwargs):
        if interval < 0 or interval > 10:
            interval = 5
        time.sleep(interval)
        self.current_return = {"operation": "do", "action": 'Wait', "kwargs": {"interval": interval}}

    def finish(self, message=None, **kwargs):
        self.is_finish = True
        self.current_return = {"operation": "finish", "action": 'finish', "kwargs": {"message": message}}