from datetime import datetime
import ast
import operator
import platform
import subprocess
import webbrowser

def get_time():
    return datetime.now().strftime("%I:%M:%S %p")

def get_date():
    return datetime.now().strftime("%A, %d %B %Y")

def calculate(expression):
    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos
    }

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value

        if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](evaluate(node.operand))

        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            left = evaluate(node.left)
            right = evaluate(node.right)

            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("Exponent too large")

            return operators[type(node.op)](left, right)

        raise ValueError("Unsupported mathematical expression")

    try:
        tree = ast.parse(expression, mode="eval")
        result = evaluate(tree.body)

        if isinstance(result, float) and not result.is_integer():
            return round(result, 8)

        return result

    except ZeroDivisionError:
        return "Cannot divide by zero."

    except (ValueError, SyntaxError, OverflowError):
        return "Invalid mathematical expression."

def open_website(url):
    allowed_urls = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://github.com"
    }

    url = url.lower().strip()

    if url not in allowed_urls:
        return "Website is not in the approved list."

    webbrowser.open(allowed_urls[url])

    return f"Opened {url} in the default browser."

def open_app(app_name):
    if platform.system() != "Windows":
        return "Application launching is currently configured for Windows."

    applications = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe"
    }

    app_name = app_name.lower().strip()

    if app_name not in applications:
        return "Application is not in the approved list."

    subprocess.Popen([applications[app_name]])

    return f"Opened {app_name}."

TOOLS = {
    "get_time": get_time,
    "get_date": get_date,
    "calculate": calculate,
    "open_website": open_website,
    "open_app": open_app
}

def execute_tool(tool_name, parameters=None):
    parameters = parameters or {}

    tool = TOOLS.get(tool_name)

    if tool is None:
        return {
            "success": False,
            "result": "Tool not available."
        }

    try:
        result = tool(**parameters)

        return {
            "success": True,
            "result": result
        }

    except TypeError:
        return {
            "success": False,
            "result": "Invalid tool parameters."
        }

    except Exception as error:
        return {
            "success": False,
            "result": str(error)
        }