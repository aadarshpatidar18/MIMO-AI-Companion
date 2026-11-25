from planner import create_plan
from tools import execute_tool

MAX_STEPS = 5

def run_agent(command):
    plan = create_plan(command)

    steps = plan.get("steps", [])

    if not isinstance(steps, list):
        return "Invalid execution plan."

    if len(steps) > MAX_STEPS:
        return "The requested plan contains too many steps."

    results = []

    for step in steps:
        if not isinstance(step, dict):
            return "Invalid step in execution plan."

        tool_name = step.get("tool")
        parameters = step.get("parameters", {})

        if not isinstance(parameters, dict):
            return "Invalid tool parameters."

        result = execute_tool(tool_name, parameters)

        results.append({
            "tool": tool_name,
            "success": result["success"],
            "result": result["result"]
        })

        if not result["success"]:
            break

    return results