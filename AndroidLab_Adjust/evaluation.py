import templates.seeact_screenshot_prompts as SeeActPrompts
import templates.seeact_xml_prompts as SeeActPrompts_xml
from evaluation.definition import *
from evaluation.utils import *
from templates import *
import json


class AutoTask():
    def __init__(self, instruction, controller, page_executor, agent, record, command_per_step, **kwargs):
        self.controller = controller
        self.page_executor = page_executor
        self.agent = agent
        self.record = record
        self.kwargs = kwargs
        self.set_system_prompt(instruction)
        self.record.command_per_step = [command_per_step]
        # pimusic and map.me need ac to fetch xml
        if "map.me" in instruction or "pimusic" in instruction:
            self.accessibility = self.controller.check_ac_survive()
        else:
            self.accessibility = False

    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": self.agent.system_prompt(instruction)
        }]

    def run_step(self, round_count):
        self.record.update_before(controller=self.controller, need_screenshot=True, ac_status=self.accessibility)
        compressed_xml_json = self.record.get_latest_xml()

        prompt = f"" if round_count == 0 else "** XML **\n"
        try:
            current_message = {"role": "user", "content": prompt + compressed_xml_json}
            if self.agent.name == "GLMModelAgent":
                current_message["current_app"] = self.controller.get_current_activity()
            rsp = self.agent.act([*self.record.history, current_message])
        except Exception as e:
            print_with_color(f"Error: {e}", "red")

        exe_res = self.page_executor(get_code_snippet(rsp))
        self.record.update_after(exe_res, rsp)
        self.record.turn_number += 1


class TextOnlyTask(AutoTask):
    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SYSTEM_PROMPT_ANDROID_TEXT_GPT + f"\n\nTask Instruction: {instruction}"
        }]


class ScreenshotTask(TextOnlyTask):
    def run_step(self, round_count):
        self.record.update_before(controller=self.controller, need_screenshot=True, ac_status=self.accessibility,
                                  need_labeled=True)
        prompt = f"" if round_count == 0 else "** XML **\n"
        try:
            xml = self.record.get_latest_xml()
            image_path = self.record.labeled_current_screenshot_path
            current_message = self.agent.prompt_to_message(prompt, [image_path])
            rsp = self.agent.act([*self.record.history, current_message])

            # rsp = input("Please input the response: ")
        except Exception as e:
            import traceback
            print(traceback.print_exc())
            # print_with_color(f"Error: {e}", "red")

        exe_res = self.page_executor(get_code_snippet(rsp))
        self.record.update_after(exe_res, rsp)
        self.record.turn_number += 1

    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SYSTEM_PROMPT_ANDROID_MLLM_DIRECT + f"\n\nTask Instruction: {instruction}"
        }]


class CogAgentTask(TextOnlyTask):
    def run_step(self, round_count):
        self.record.update_before(controller=self.controller, need_screenshot=True, ac_status=self.accessibility,
                                  need_labeled=True)
        prompt = f"" if round_count == 0 else json.dumps({"current_app": self.controller.get_current_app()},
                                                         ensure_ascii=False)
        try:
            image_path = self.page_executor.current_screenshot
            current_message = self.agent.prompt_to_message(prompt, [image_path])
            rsp = self.agent.act([*self.record.history, current_message])
        except Exception as e:
            import traceback
            print(traceback.print_exc())
            # print_with_color(f"Error: {e}", "red")

        exe_res = self.page_executor(get_code_snippet(rsp))
        self.record.update_after(exe_res, rsp)
        self.record.turn_number += 1

    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SYSTEM_PROMPT_ANDROID_MLLM_CogAgent + f"\n\nTask Instruction: {instruction}"
        }]


class ScreenshotReactTask(ScreenshotTask):
    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SYSTEM_PROMPT_ANDROID_MLLM_DIRECT_REACT + f"\n\nTask Instruction: {instruction}"
        }]


class ScreenSeeActTask(TextOnlyTask):

    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SeeActPrompts.QUERY_SYSTEM_PROMPT
        }]
        self.stage_one_record = []
        self.instruction = instruction

    def run_step(self, round_count):
        self.record.update_before(controller=self.controller, need_screenshot=True, ac_status=self.accessibility,
                                  need_labeled=False)
        try:
            xml_tree = self.record.get_latest_xml_tree()
            choices_list = extract_bounds(xml_tree)
            image_path = self.page_executor.current_screenshot
            system_prompt = SeeActPrompts.QUERY_SYSTEM_PROMPT
            query_user_prompt = SeeActPrompts.QUERY_USER_PROMPT.format(
                task=self.instruction,
                previous_actions=("\n\n".join(self.stage_one_record) or "None")
            )
            query_message = self.agent.prompt_to_message(query_user_prompt, [image_path])
            referring_user_prompt = SeeActPrompts.REFERRING_USER_PROMPT.format(
                option_prompt="\n".join(f"{item['key']} | {item['value']}" for item in choices_list)
            )

            messages = [
                {"role": "system", "content": system_prompt},
                query_message,
            ]

            # Stage 1. Query
            print(">> Stage 1. Query")
            with open("monitor.log", "w") as f:
                f.write(json.dumps(messages, indent=4))
            description = self.agent.act(messages)
            print(description, end="\n\n")
            with open("monitor.log", "w") as f:
                f.write(description)
            messages.append({"role": "assistant", "content": description})
            messages.append({"role": "user", "content": referring_user_prompt})

            # Stage 2. Referring
            print(">> Stage 2. Referring")
            with open("monitor.log", "w") as f:
                f.write(json.dumps(messages, indent=4))

            referring = self.agent.act(messages)
            print(referring, end="\n\n")
            with open("monitor.log", "w") as f:
                f.write(referring)


        except Exception as e:
            import traceback
            print(traceback.print_exc())
            # print_with_color(f"Error: {e}", "red")
            # exit(1)
        referring = referring.split("Final Answer:")[-1].strip()
        exe_res = self.page_executor(get_code_snippet(referring))
        self.stage_one_record.append(description)
        self.record.update_after(exe_res, description + "\n\n==========\n\n" + referring)
        self.record.turn_number += 1


class TextOnlySeeActTask(TextOnlyTask):

    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SeeActPrompts_xml.QUERY_SYSTEM_PROMPT
        }]
        self.stage_one_record = []
        self.instruction = instruction

    def run_step(self):
        self.record.update_before(controller=self.controller, need_screenshot=True, ac_status=self.accessibility,
                                  need_labeled=False)
        round_count = self.record.get_round_count()
        try:
            xml_tree = self.record.get_latest_xml_tree()
            xml_text = self.record.get_latest_xml()
            choices_list = extract_bounds(xml_tree)
            image_path = self.page_executor.current_screenshot
            system_prompt = SeeActPrompts_xml.QUERY_SYSTEM_PROMPT
            query_user_prompt = SeeActPrompts_xml.QUERY_USER_PROMPT.format(
                task=self.instruction,
                previous_actions=("\n\n".join(self.stage_one_record) or "None"),
                xml_compressed=xml_text
            )
            query_message = {"role": "user", "content": query_user_prompt}

            referring_user_prompt = SeeActPrompts_xml.REFERRING_USER_PROMPT.format(
                option_prompt="\n".join(f"{item['key']} | {item['value']}" for item in choices_list)
            )

            messages = [
                {"role": "system", "content": system_prompt},
                query_message,
            ]

            # Stage 1. Query
            print(">> Stage 1. Query")
            with open("monitor.log", "w") as f:
                f.write(json.dumps(messages, indent=4))
            description = self.agent.act(messages)
            print(description, end="\n\n")
            with open("monitor.log", "w") as f:
                f.write(description)
            messages.append({"role": "assistant", "content": description})
            messages.append({"role": "user", "content": referring_user_prompt})

            # Stage 2. Referring
            print(">> Stage 2. Referring")
            with open("monitor.log", "w") as f:
                f.write(json.dumps(messages, indent=4))

            referring = self.agent.act(messages)
            print(referring, end="\n\n")
            with open("monitor.log", "w") as f:
                f.write(referring)


        except Exception as e:
            import traceback
            print(traceback.print_exc())
            # print_with_color(f"Error: {e}", "red")
            # exit(1)
        referring = referring.split("Final Answer:")[-1].strip()
        exe_res = self.page_executor(get_code_snippet(referring))
        self.stage_one_record.append(description)
        self.record.update_after(exe_res, description + "\n\n==========\n\n" + referring)
        self.record.turn_number += 1


class TextOnlyReactTask(TextOnlyTask):
    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SYSTEM_PROMPT_ANDROID_TEXT_ReAct + f"\n\nTask Instruction: {instruction}"
        }]


class TextOnlyFineTuneTask(TextOnlyTask):
    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SYSTEM_PROMPT_ANDROID_TEXT_GLM_v1_5 + f"\n\nTask Instruction: {instruction}"
        }]

    def run_step(self, round_count):
        self.record.update_before(controller=self.controller, need_screenshot=True, ac_status=self.accessibility)
        compressed_xml_json = self.record.get_latest_xml()

        # prompt = f"" if round_count == 0 else "** XML **\n"
        try:
            app_info = f"{json.dumps({'current_app': self.controller.get_current_app()}, ensure_ascii=False)}\n"
            current_message = {"role": "user", "content": app_info + compressed_xml_json}
            rsp = self.agent.act([*self.record.history, current_message])
        except Exception as e:
            print_with_color(f"Error: {e}", "red")

        exe_res = self.page_executor(get_code_snippet(rsp))
        self.record.update_after(exe_res, rsp)
        self.record.turn_number += 1


class TextOnlyFineTuneTask_long(TextOnlyFineTuneTask):
    def set_system_prompt(self, instruction):
        self.record.history = [{
            "role": "system",
            "content": SYSTEM_PROMPT_ANDROID_TEXT_GPT + f"\n\nTask Instruction: {instruction}"
        }]


# 增加项
class OriginalImageJSONVisionTask_Qwen2_5_vl(ScreenshotTask):

    def set_system_prompt(self, instruction):
        #  获取屏幕尺寸
        try:
            width, height = self.controller.get_device_size()
        except Exception:
            width, height = 1440, 3120
            print_with_color(f"[警告] 无法获取设备分辨率，使用默认值 {width}x{height}", "yellow")

        # 避免 Prompt 中 JSON 花括号引起的 KeyError

        formatted_prompt = SYSTEM_PROMPT_QWEN2_5_VL_IMAGE_JSON.replace("{task_description}", str(instruction)) \
            .replace("{screen_width}", str(width)) \
            .replace("{screen_height}", str(height))

        self.record.history = [{
            "role": "system",
            "content": formatted_prompt
        }]

    def run_step(self, round_count):
        # 我们需要原始截图给模型，但仍需生成控件列表用于坐标映射
        self.record.update_before(
            controller=self.controller,
            need_screenshot=True,
            ac_status=self.accessibility,
            need_labeled=True
        )

        prompt = ""
        try:
            # 传递原始截图（不带标记）
            image_path = self.page_executor.current_screenshot
            current_message = self.agent.prompt_to_message(prompt, [image_path])
            rsp = self.agent.act([*self.record.history, current_message])
        except Exception as e:
            import traceback
            traceback.print_exc()
            rsp = '{"action_type": "wait"}'

        python_code = self.translate_json_to_vision_code(rsp)

        print_with_color(f"\n[Model JSON]: {rsp}", "cyan")
        print_with_color(f"[Exec Code]: {python_code}\n", "green")

        exe_res = self.page_executor(python_code)
        self.record.update_after(exe_res, rsp)
        self.record.turn_number += 1

    def translate_json_to_vision_code(self, json_str: str) -> str:
        """
        - 支持标准 Android_control action_space
        """

        if "```" in json_str:
            blocks = re.findall(r"```(?:json)?\s*([\s\S]+?)\s*```", json_str)
            if blocks:
                json_str = blocks[0]

        # 提取 JSON 区间
        start_idx = json_str.find('{')
        end_idx = json_str.rfind('}')
        if start_idx == -1 or end_idx == -1:
            return "wait()"

        json_content = json_str[start_idx:end_idx + 1]

        # 清洗 JSON
        try:
            clean = json_content.strip().replace("'", '"')
            clean = re.sub(r",\s*([}\]])", r"\1", clean)
            action_dict = json.loads(clean)
        except:
            return "wait()"

        action_type = action_dict.get("action_type", "").lower()

        # =====================
        # CLICK / LONG PRESS
        # =====================
        if action_type in ["click", "long_press"]:
            try:
                x = int(float(action_dict.get("x", -1)))
                y = int(float(action_dict.get("y", -1)))
            except:
                return "wait()"

            if x < 0 or y < 0:
                return "wait()"

            elem_list = getattr(self.page_executor, "elem_list", [])
            if not elem_list:
                return "wait()"

            best_index, min_score = -1, float('inf')
            for i, elem in enumerate(elem_list):
                try:
                    (x1, y1), (x2, y2) = elem.bbox
                    if x1 <= x <= x2 and y1 <= y <= y2:
                        area = (x2 - x1) * (y2 - y1)
                        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                        dist = (x - cx) ** 2 + (y - cy) ** 2
                        score = area + dist
                        if score < min_score:
                            min_score = score
                            best_index = i + 1
                except:
                    continue

            if best_index != -1:
                return f"tap({best_index})" if action_type == "click" else f"long_press({best_index})"

            return "wait()"

        # =====================
        # SCROLL
        # =====================
        elif action_type == "scroll":
            direction = action_dict.get("direction", "down").lower()
            direction_map = {"up": "down", "down": "up", "left": "right", "right": "left"}
            swipe_dir = direction_map.get(direction, "up")
            return f"swipe(direction='{swipe_dir}', dist='long')"

        # =====================
        # INPUT TEXT
        # =====================
        elif action_type in ["input_text", "type"]:
            text = action_dict.get("text", "")
            return f"type(input_str={json.dumps(text)})"

        # =====================
        # NAVIGATION
        # =====================
        elif action_type == "navigate_home":
            return "home()"

        elif action_type == "navigate_back":
            return "back()"

        # =====================
        # WAIT
        # =====================
        elif action_type == "wait":
            return "wait()"

        # =====================
        # FINISH
        # =====================
        elif action_type == "finish":
            return f"finish(message={json.dumps(action_dict.get('message', 'Done'))})"

        return "wait()"


class OriginalImageJSONVisionTask_Qwen3_vl(ScreenshotTask):

    def set_system_prompt(self, instruction):
        # 1. 获取并保存屏幕尺寸，用于后续的坐标转换
        try:
            width, height = self.controller.get_device_size()
        except Exception:
            width, height = 1440, 3120
            print_with_color(f"[警告] 无法获取设备分辨率，使用默认值 {width}x{height}", "yellow")

        # 保存宽高到实例变量中（关键修改）
        self.screen_width = width
        self.screen_height = height

        formatted_prompt = SYSTEM_PROMPT_QWEN3_VL_IMAGE_JSON.replace("{task_description}", str(instruction)) \
            .replace("{screen_width}", str(width)) \
            .replace("{screen_height}", str(height))

        self.record.history = [{
            "role": "system",
            "content": formatted_prompt
        }]

    def run_step(self, round_count):
        self.record.update_before(
            controller=self.controller,
            need_screenshot=True,
            ac_status=self.accessibility,
            need_labeled=True
        )

        prompt = ""
        try:
            image_path = self.page_executor.current_screenshot
            current_message = self.agent.prompt_to_message(prompt, [image_path])
            rsp = self.agent.act([*self.record.history, current_message])
        except Exception as e:
            import traceback
            traceback.print_exc()
            rsp = '{"action_type": "wait"}'

        python_code = self.translate_json_to_vision_code(rsp)

        print_with_color(f"\n[Model JSON (Qwen3)]: {rsp}", "cyan")
        print_with_color(f"[Exec Code]: {python_code}\n", "green")

        exe_res = self.page_executor(python_code)
        self.record.update_after(exe_res, rsp)
        self.record.turn_number += 1

    def translate_json_to_vision_code(self, json_str: str) -> str:
        """
        包含 Qwen3 归一化坐标 (0-1000) 到 绝对像素坐标 的转换逻辑
        """
        if "```" in json_str:
            blocks = re.findall(r"```(?:json)?\s*([\s\S]+?)\s*```", json_str)
            if blocks:
                json_str = blocks[0]

        start_idx = json_str.find('{')
        end_idx = json_str.rfind('}')
        if start_idx == -1 or end_idx == -1:
            return "wait()"

        json_content = json_str[start_idx:end_idx + 1]

        try:
            clean = json_content.strip().replace("'", '"')
            clean = re.sub(r",\s*([}\]])", r"\1", clean)
            action_dict = json.loads(clean)
        except:
            return "wait()"

        action_type = action_dict.get("action_type", "").lower()

        # =====================
        # CLICK / LONG PRESS
        # =====================
        if action_type in ["click", "long_press"]:
            try:
                # 1. 拿到 0-1000 的归一化坐标
                norm_x = float(action_dict.get("x", -1))
                norm_y = float(action_dict.get("y", -1))
            except:
                return "wait()"

            # 校验归一化坐标范围 (容错一点，允许边界稍微超出)
            if norm_x < -10 or norm_y < -10 or norm_x > 1010 or norm_y > 1010:
                print_with_color(f"[警告] Qwen3 归一化坐标超出范围: x={norm_x}, y={norm_y}", "yellow")
                return "wait()"

            # 2. 核心转换：归一化坐标 -> 绝对像素坐标
            abs_x = (norm_x / 1000.0) * self.screen_width
            abs_y = (norm_y / 1000.0) * self.screen_height

            elem_list = getattr(self.page_executor, "elem_list", [])
            if not elem_list:
                return "wait()"

            best_index, min_score = -1, float('inf')
            for i, elem in enumerate(elem_list):
                try:
                    (x1, y1), (x2, y2) = elem.bbox
                    # 判断转换后的绝对坐标是否落在控件框内
                    if x1 <= abs_x <= x2 and y1 <= abs_y <= y2:
                        area = (x2 - x1) * (y2 - y1)
                        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                        # 计算距离（使用绝对坐标）
                        dist = (abs_x - cx) ** 2 + (abs_y - cy) ** 2
                        score = area + dist
                        if score < min_score:
                            min_score = score
                            best_index = i + 1
                except:
                    continue

            if best_index != -1:
                return f"tap({best_index})" if action_type == "click" else f"long_press({best_index})"

            # 如果没有匹配到控件，可以在这里返回基于绝对坐标的原生点击作为兜底
            print_with_color(f"[未匹配控件] 退化为原生坐标点击: ({int(abs_x)}, {int(abs_y)})", "yellow")
            return f"self.controller.tap({int(abs_x)}, {int(abs_y)})" if action_type == "click" else f"self.controller.long_press({int(abs_x)}, {int(abs_y)})"

        # =====================
        # SCROLL
        # =====================
        elif action_type == "scroll":
            direction = action_dict.get("direction", "down").lower()
            direction_map = {"up": "down", "down": "up", "left": "right", "right": "left"}
            swipe_dir = direction_map.get(direction, "up")
            return f"swipe(direction='{swipe_dir}', dist='long')"

        # =====================
        # INPUT TEXT
        # =====================
        elif action_type in ["input_text", "type"]:
            text = action_dict.get("text", "")
            return f"type(input_str={json.dumps(text)})"

        # =====================
        # NAVIGATION
        # =====================
        elif action_type == "navigate_home":
            return "home()"

        elif action_type == "navigate_back":
            return "back()"

        # =====================
        # WAIT
        # =====================
        elif action_type == "wait":
            return "wait()"

        # =====================
        # FINISH
        # =====================
        elif action_type == "finish":
            return f"finish(message={json.dumps(action_dict.get('message', 'Done'))})"

        return "wait()"
