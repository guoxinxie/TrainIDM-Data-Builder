import sys
import re
from openai import OpenAI
from zhipuai import ZhipuAI
from agent import *
from utils_mobile.and_controller import AndroidController, list_all_devices
from utils_mobile.utils import print_with_color


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def get_code_snippet(content):
    code = re.search(r'```.*?([\s\S]+?)```', content)
    if code is None:
        return content
        # print(content)
        # raise RuntimeError("No available code found!")
    code = code.group(1).strip()
    code = code.split("\n")[-1]

    return code


def handle_backoff(details):
    print(f"Retry {details['tries']} for Exception: {details['exception']}")


def handle_giveup(details):
    print(f"Gave up after {details['tries']} tries calling function {details['target'].__name__}")




def detect_answer(question: str, model_answer: str, standard_answer: str, args):
    detect_prompt = f"You need to judge the model answer is True or False based on Standard Answer we provided. You should whether answer [True] or [False]. \n\nQuestion: {question}\n\nModel Answer: {model_answer}\n\nStandard Answer: {standard_answer}"

    call_time = 0
    while call_time <= 5:
        call_time += 1
        if args.judge_model == "glm4":
            return_message = get_completion_glm(prompt=detect_prompt, glm4_key=args.api_key)
        else:
            #
            return_message = get_completion_gpt(
                prompt=detect_prompt,
                model_name=args.judge_model,
                api_key=args.api_key,
                api_base=args.api_base
            )

        if "True" in return_message:
            return True
        elif "False" in return_message:
            return False
    return False


def detect_answer_test(args):
    detect_prompt = "hello! who are you"
    print(f"Testing judge model: {args.judge_model}...")

    if args.judge_model == "glm4":
        res = get_completion_glm(detect_prompt, args.api_key)
    else:

        res = get_completion_gpt(detect_prompt, args.judge_model, args.api_key, args.api_base)

    print(f"Judge model response: {res}")
    if not isinstance(res, str):
        print("ERROR: Judge model error!")
        sys.exit()


@backoff.on_exception(backoff.expo, Exception, max_tries=5, on_backoff=handle_backoff, giveup=handle_giveup)
def get_completion_gpt(prompt, model_name, api_key=None, api_base=None):

    client = OpenAI(
        api_key=api_key if api_key else os.environ.get("OPENAI_API_KEY"),
        base_url=api_base if api_base else "https://api.openai.com/v1"
    )

    messages = [{"role": "user", "content": prompt}]
    r = client.chat.completions.create(
        model=model_name,
        messages=messages,
        max_tokens=512,
        temperature=0.001
    )
    return r.choices[0].message.content


def detect_answer_test(args):
    detect_prompt = "hello! are you ready?"
    print(f"Testing judge model: {args.judge_model} via {args.api_base or 'OpenAI Default'}...")

    try:
        if args.judge_model == "glm4":
            res = get_completion_glm(detect_prompt, args.api_key)
        else:
            res = get_completion_gpt(detect_prompt, args.judge_model, args.api_key, args.api_base)
        print(f"Judge model response: {res}")
    except Exception as e:
        print(f"ERROR: Judge model test failed: {e}")
        sys.exit()

@backoff.on_exception(backoff.expo,
                      Exception,
                      max_tries=5,
                      on_backoff=handle_backoff,
                      on_giveup=handle_giveup)  # 关键修改：giveup 改为 on_giveup
def get_completion_glm(prompt, glm4_key):
    client = ZhipuAI(api_key=glm4_key)
    response = client.chat.completions.create(
        model="glm-4",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


@backoff.on_exception(backoff.expo,
                      Exception,
                      max_tries=5,
                      on_backoff=handle_backoff,
                      on_giveup=handle_giveup)  # 关键修改：giveup 改为 on_giveup
def get_completion_gpt(prompt, model_name, api_key=None, api_base=None):
    client = OpenAI(
        api_key=api_key if api_key else os.environ.get("OPENAI_API_KEY", "empty"),
        base_url=api_base if api_base else "https://api.openai.com/v1"
    )

    messages = [{"role": "user", "content": prompt}]
    r = client.chat.completions.create(
        model=model_name,
        messages=messages,
        max_tokens=512,
        temperature=0.0  # 建议改为 0.0，有些本地接口不支持 0.001 这种精细浮点
    )
    return r.choices[0].message.content


def get_mobile_device():
    device_list = list_all_devices()
    if not device_list:
        print_with_color("ERROR: No device found!", "red")
        sys.exit()
    print_with_color(f"List of devices attached:\n{str(device_list)}", "yellow")
    if len(device_list) == 1:
        device = device_list[0]
        print_with_color(f"Device selected: {device}", "yellow")
    else:
        print_with_color("Please choose the Android device to start demo by entering its ID:", "blue")
        device = input()

    controller = AndroidController(device)
    width, height = controller.get_device_size()
    if not width and not height:
        print_with_color("ERROR: Invalid device size!", "red")
        sys.exit()
    print_with_color(f"Screen resolution of {device}: {width}x{height}", "yellow")

    return controller


def get_mobile_device_and_name():
    device_list = list_all_devices()
    if not device_list:
        print_with_color("ERROR: No device found!", "red")
        sys.exit()
    print_with_color(f"List of devices attached:\n{str(device_list)}", "yellow")
    if len(device_list) == 1:
        device = device_list[0]
        print_with_color(f"Device selected: {device}", "yellow")
    else:
        print_with_color("Please choose the Android device to start demo by entering its ID:", "blue")
        device = input()

    controller = AndroidController(device)
    width, height = controller.get_device_size()
    if not width and not height:
        print_with_color("ERROR: Invalid device size!", "red")
        sys.exit()
    print_with_color(f"Screen resolution of {device}: {width}x{height}", "yellow")

    return controller, device


# 增加项
def convert_json_to_python_code(json_str):
    """
     - 支持标准 Android_control action_space
    """

    match = re.search(r"\{.*\}", json_str, re.DOTALL)
    if not match:
        return "do(action='Wait')"

    json_str = match.group(0)

    try:
        clean = json_str.strip().replace("'", '"')
        clean = re.sub(r",\s*([}\]])", r"\1", clean)
        data = json.loads(clean)
    except:
        data = None

    def regex_get(pattern):
        m = re.search(pattern, json_str, re.IGNORECASE)
        return m.group(1).strip() if m else None

    action_type = data.get("action_type") if data else regex_get(r'"action_type"\s*:\s*"([^"]+)"')
    if not action_type:
        return "do(action='Wait')"

    action_type = action_type.lower()

    # =====================
    # CLICK / LONG PRESS
    # =====================
    if action_type in ["click", "long_press"]:
        x = data.get("x") if data else regex_get(r'"x"\s*:\s*([\d.]+)')
        y = data.get("y") if data else regex_get(r'"y"\s*:\s*([\d.]+)')

        try:
            x = int(float(x))
            y = int(float(y))
            if x < 0 or y < 0:
                return "do(action='Wait')"
        except:
            return "do(action='Wait')"

        action_name = "Tap" if action_type == "click" else "Long Press"
        return f'do(action="{action_name}", element=[{x - 1}, {y - 1}, {x + 1}, {y + 1}])'

    # =====================
    # SCROLL
    # =====================
    elif action_type == "scroll":
        direction = data.get("direction") if data else regex_get(r'"direction"\s*:\s*"([^"]+)"')
        if not direction:
            return "do(action='Wait')"

        direction = direction.lower()
        if direction not in ["up", "down", "left", "right"]:
            return "do(action='Wait')"

        return f'do(action="Swipe", direction="{direction}")'

    # =====================
    # INPUT TEXT
    # =====================
    elif action_type == "input_text":
        text = data.get("text", "") if data else regex_get(r'"text"\s*:\s*"((?:\\"|[^"])*)"') or ""
        text = text.replace('"', '\\"')
        return f'do(action="Type", text="{text}")'

    # =====================
    # NAVIGATION
    # =====================
    elif action_type == "navigate_home":
        return 'do(action="Home")'

    elif action_type == "navigate_back":
        return 'do(action="Back")'

    # =====================
    # WAIT
    # =====================
    elif action_type == "wait":
        return 'do(action="Wait")'

    # =====================
    # FINISH
    # =====================
    elif action_type == "finish":
        message = data.get("message", "Task completed") if data else "Task completed"
        message = message.replace('"', '\\"')
        return f'finish(message="{message}")'

    return "do(action='Wait')"
