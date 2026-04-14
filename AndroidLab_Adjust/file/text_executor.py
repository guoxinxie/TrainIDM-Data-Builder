import inspect
import json
import re
import time
import os
from functools import partial

from templates.packages import find_package
from .utils import call_dino, plot_bbox


def remove_leading_zeros_in_string(s):
    # 使用正则表达式匹配列表中的每个数值并去除前导零
    return re.sub(r'\b0+(\d)', r'\1', s)


class TextOnlyExecutor:
    def __init__(self, controller, config):
        self.config = config
        self.controller = controller
        self.device = controller.device
        self.screenshot_dir = config.screenshot_dir
        self.task_id = int(time.time())

        self.new_page_captured = False
        self.current_screenshot = None
        self.current_return = None

        self.last_turn_element = None
        self.last_turn_element_tagname = None
        self.is_finish = False
        self.device_pixel_ratio = None
        self.latest_xml = None

    def __get_current_status__(self):
        status = {
            "Current Activity": self.controller.get_current_activity(),
        }
        return json.dumps(status, ensure_ascii=False)

    def modify_relative_bbox(self, relative_bbox):
        viewport_width, viewport_height = self.controller.viewport_size
        modify_x1 = relative_bbox[0] * viewport_width / 1000
        modify_y1 = relative_bbox[1] * viewport_height / 1000
        modify_x2 = relative_bbox[2] * viewport_width / 1000
        modify_y2 = relative_bbox[3] * viewport_height / 1000
        return [modify_x1, modify_y1, modify_x2, modify_y2]

    def __call__(self, code_snippet):
        self.current_return = None  # Reset the return value for each call

        local_context = self.__get_class_methods__(exclude_inherited=False) 
        local_context.update(**{'self': self})

        # 提取 Action: 后面的代码
        if len(code_snippet.split("\n")) > 1:
            for code in code_snippet.split("\n"):
                if "Action: " in code:
                    code_snippet = code.split("Action: ")[1]
                    break

        code = remove_leading_zeros_in_string(code_snippet.strip())
        print(f"Executing code: {code}")  # 增加日志
        try:
            exec(code, {}, local_context)
        except Exception as e:
            print(f"[ERROR] Executing code failed: {e}")
            # 如果执行失败，可以设置一个默认的失败返回
            self.current_return = {"operation": "error", "action": 'ExecutionError', "kwargs": {"error": str(e)}}

        return self.current_return

    def __get_class_methods__(self, include_dunder=False, exclude_inherited=True):
        """
        获取类的方法字典，并添加别名，用于 exec 的执行上下文。
        """
        methods_dict = {}
        cls = self.__class__
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if exclude_inherited and method.__qualname__.split('.')[0] != cls.__name__:
                continue
            if not include_dunder and name.startswith('__'):
                continue
            methods_dict[name] = partial(method, self)

        # --- 在这里添加函数别名以兼容不同模型的输出 ---
        if 'finish' in methods_dict:
            methods_dict['finished'] = methods_dict['finish']
        if 'tap' in methods_dict:
            methods_dict['click'] = methods_dict['tap']

        return methods_dict

    def update_screenshot(self, prefix=None, suffix=None):
        timestamp = time.time()
        if prefix is None and suffix is None:
            filename = f"screenshot-{timestamp}.png"
        elif prefix is not None and suffix is None:
            filename = f"screenshot-{prefix}-{timestamp}.png"
        elif prefix is None and suffix is not None:
            filename = f"screenshot-{timestamp}-{suffix}.png"
        else:
            filename = f"screenshot-{prefix}-{timestamp}-{suffix}.png"
        self.current_screenshot = os.path.join(self.screenshot_dir, filename)
        self.controller.save_screenshot(self.current_screenshot)

   # page_executor/text_executor.py

    def do(self, action=None, element=None, **kwargs):
        # 1. 定义目前真正支持的动作列表
        supported_actions = ["Tap", "Type", "Swipe", "Enter", "Home", "Back", "Long Press", "Wait", "Launch"]
        assert action in supported_actions, f"Unsupported Action: {action}"
        
        if self.config.is_relative_bbox and element is not None:
            element = self.modify_relative_bbox(element)
            
        # 2. 修改映射表，移除 Call_API (因为它被注释掉了)
        action_map = {
            "Tap": self.tap,
            "Type": self.type,
            "Swipe": self.swipe,
            "Enter": self.press_enter,
            "Home": self.press_home,
            "Back": self.press_back,
            "Long Press": self.long_press,
            "Wait": self.wait,
            "Launch": self.launch
            # "Call_API": self.call_api  <-- 不要在这里引用被注释的方法
        }

        # 3. 执行动作
        if action in ["Tap", "Long Press", "Swipe"]:
            action_map[action](element=element, **kwargs)
        elif action in ["Type", "Launch"]:
             action_map[action](**kwargs)
        else:
            action_map[action]()

    def get_relative_bbox_center(self, instruction, screenshot):
        relative_bbox = call_dino(instruction, screenshot)
        viewport_width, viewport_height = self.controller.get_device_size()

        center_x = (relative_bbox[0] + relative_bbox[2]) / 2 * viewport_width / 1000
        center_y = (relative_bbox[1] + relative_bbox[3]) / 2 * viewport_height / 1000
        width_x = (relative_bbox[2] - relative_bbox[0]) * viewport_width / 1000
        height_y = (relative_bbox[3] - relative_bbox[1]) * viewport_height / 1000

        plot_bbox([int(center_x - width_x / 2), int(center_y - height_y / 2), int(width_x), int(height_y)], screenshot,
                  instruction)
        return (int(center_x), int(center_y)), relative_bbox

    def tap(self, element=None, start_box=None):
        if start_box:
            try:
                match = re.search(r'\((\d+)[,\s]+(\d+)\)', start_box)
                if match:
                    center_x, center_y = int(match.group(1)), int(match.group(2))
                else:
                    raise ValueError(f"Invalid start_box format: {start_box}")
            except Exception as e:
                print(f"[WARN] Failed to parse start_box '{start_box}': {e}")
                self.current_return = {"operation": "do", "action": 'Wait'}
                return
        elif isinstance(element, list) and len(element) == 4:
            center_x = (element[0] + element[2]) / 2
            center_y = (element[1] + element[3]) / 2
        elif isinstance(element, list) and len(element) == 2:
            center_x, center_y = element
        elif element is None:
            raise ValueError("Tap action requires 'element' or 'start_box' argument.")
        else:
            raise ValueError(f"Invalid element format for tap: {element}")

        self.controller.tap(center_x, center_y)
        self.current_return = {"operation": "do", "action": 'Tap', "kwargs": {"element": [center_x, center_y]}}

    def long_press(self, element):
        if isinstance(element, list) and len(element) == 4:
            center_x = (element[0] + element[2]) / 2
            center_y = (element[1] + element[3]) / 2
        elif isinstance(element, list) and len(element) == 2:
            center_x, center_y = element
        else:
            raise ValueError("Invalid element format for long_press")
        self.controller.long_press(center_x, center_y)
        self.current_return = {"operation": "do", "action": 'Long Press', "kwargs": {"element": element}}

    def swipe(self, element=None, **kwargs):
        if element is None:
            center_x, center_y = self.controller.width // 2, self.controller.height // 2
        elif isinstance(element, list) and len(element) == 4:
            center_x = (element[0] + element[2]) / 2
            center_y = (element[1] + element[3]) / 2
        elif isinstance(element, list) and len(element) == 2:
            center_x, center_y = element
        else:
            raise ValueError("Invalid element format for swipe")

        assert "direction" in kwargs, "direction is required for swipe"
        direction = kwargs.get("direction")
        dist = kwargs.get("dist", "medium")
        self.controller.swipe(center_x, center_y, direction, dist)
        self.current_return = {"operation": "do", "action": 'Swipe',
                               "kwargs": {"element": [center_x, center_y], "direction": direction, "dist": dist}}
        time.sleep(1)

    def type(self, **kwargs):
        assert "text" in kwargs, "text is required for type"
        instruction = kwargs.get("text")
        self.controller.text(instruction)
        # self.controller.enter() # Typing should not automatically press enter
        self.current_return = {"operation": "do", "action": 'Type',
                               "kwargs": {"text": instruction}}

    def press_enter(self):
        self.controller.enter()
        self.current_return = {"operation": "do", "action": 'Enter'}

    def press_back(self):
        self.controller.back()
        self.current_return = {"operation": "do", "action": 'Back'}

    def press_home(self):
        self.controller.home()
        self.current_return = {"operation": "do", "action": 'Home'}

    def finish(self, message=None):
        self.is_finish = True
        self.current_return = {"operation": "finish", "action": 'finish', "kwargs": {"message": message}}

    def wait(self):
        time.sleep(3)  # Reduced wait time slightly
        self.current_return = {"operation": "do", "action": 'Wait'}

    def launch(self, **kwargs):
        assert "app" in kwargs, "app is required for launch"
        app = kwargs.get("app")
        package = find_package(app)  # find_package can raise error, let it propagate
        self.controller.launch_app(package)
        self.current_return = {"operation": "do", "action": 'Launch',
                               "kwargs": {"package": package, "app_name": app}}