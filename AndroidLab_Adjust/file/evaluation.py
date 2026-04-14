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
        # 获取屏幕尺寸
        try:
            width, height = self.controller.get_device_size()
        except Exception:
            width, height = 1440, 3120
            print_with_color(f"无法获取设备分辨率，使用默认值 {width}x{height}", "yellow")

        # 简单的替换逻辑，不涉及动态历史更新
        formatted_prompt = SYSTEM_PROMPT_QWEN2_5_VL_IMAGE_JSON.replace("{task_description}", str(instruction)) \
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

        print_with_color(f"\n[Model JSON]: {rsp}", "cyan")
        print_with_color(f"[Exec Code]: {python_code}\n", "green")

        exe_res = self.page_executor(python_code)
        self.record.update_after(exe_res, rsp)
        self.record.turn_number += 1

    def translate_json_to_vision_code(self, json_str: str) -> str:
        # 基础提取
        match = re.search(r"\{.*\}", json_str, re.DOTALL)
        if not match:
            return "wait()"
        json_content = match.group(0)

        try:
            clean = json_content.strip().replace("'", '"')
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

            # 未匹配到控件时，使用 do 方法退化执行，以确保返回 p_act 字典
            act_name = "Tap" if action_type == "click" else "Long Press"
            return f"do(action='{act_name}', element=[{x}, {y}])"

        elif action_type == "scroll":
            direction = action_dict.get("direction", "down").lower()
            direction_map = {"up": "down", "down": "up", "left": "right", "right": "left"}
            swipe_dir = direction_map.get(direction, "up")
            return f"swipe(direction='{swipe_dir}', dist='long')"

        elif action_type in ["input_text", "type"]:
            text = action_dict.get("text", "")
            return f"type(input_str={json.dumps(text)})"

        elif action_type == "navigate_home":
            return "home()"

        elif action_type == "navigate_back":
            return "back()"

        elif action_type == "wait":
            return "wait()"

        elif action_type == "finish":
            return f"finish(message={json.dumps(action_dict.get('message', 'Done'))})"

        return "wait()"


class OriginalImageJSONVisionTask_Qwen3_vl(ScreenshotTask):

    def set_system_prompt(self, instruction):
        try:
            width, height = self.controller.get_device_size()
        except Exception:
            width, height = 1440, 3120
            print_with_color(f"无法获取设备分辨率，使用默认值 {width}x{height}", "yellow")

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
        match = re.search(r"\{.*\}", json_str, re.DOTALL)
        if not match:
            return "wait()"
        json_content = match.group(0)

        try:
            clean = json_content.strip().replace("'", '"')
            action_dict = json.loads(clean)
        except:
            return "wait()"

        action_type = action_dict.get("action_type", "").lower()

        if action_type in ["click", "long_press"]:
            try:
                norm_x = float(action_dict.get("x", -1))
                norm_y = float(action_dict.get("y", -1))
            except:
                return "wait()"

            if norm_x < -10 or norm_y < -10 or norm_x > 1010 or norm_y > 1010:
                return "wait()"

            abs_x = (norm_x / 1000.0) * self.screen_width
            abs_y = (norm_y / 1000.0) * self.screen_height

            elem_list = getattr(self.page_executor, "elem_list", [])
            best_index, min_score = -1, float('inf')
            for i, elem in enumerate(elem_list):
                try:
                    (x1, y1), (x2, y2) = elem.bbox
                    if x1 <= abs_x <= x2 and y1 <= abs_y <= y2:
                        area = (x2 - x1) * (y2 - y1)
                        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                        dist = (abs_x - cx) ** 2 + (abs_y - cy) ** 2
                        score = area + dist
                        if score < min_score:
                            min_score = score
                            best_index = i + 1
                except:
                    continue

            if best_index != -1:
                return f"tap({best_index})" if action_type == "click" else f"long_press({best_index})"

            # 未匹配到控件时，使用 do 方法退化执行，防止 update_after 返回 None
            act_name = "Tap" if action_type == "click" else "Long Press"
            return f"do(action='{act_name}', element=[{int(abs_x)}, {int(abs_y)}])"

        elif action_type == "scroll":
            direction = action_dict.get("direction", "down").lower()
            direction_map = {"up": "down", "down": "up", "left": "right", "right": "left"}
            swipe_dir = direction_map.get(direction, "up")
            return f"swipe(direction='{swipe_dir}', dist='long')"

        elif action_type in ["input_text", "type"]:
            text = action_dict.get("text", "")
            return f"type(input_str={json.dumps(text)})"

        elif action_type == "navigate_home":
            return "home()"

        elif action_type == "navigate_back":
            return "back()"

        elif action_type == "wait":
            return "wait()"

        elif action_type == "finish":
            return f"finish(message={json.dumps(action_dict.get('message', 'Done'))})"

        return "wait()"