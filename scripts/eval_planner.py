"""Measure how reliably YOUR configured model plans tool use.

Run from the project root with Ollama (and optionally Gemini) available:
    python -m scripts.eval_planner            # uses the router's 'plan' route
    python -m scripts.eval_planner --local    # force Ollama only
Prints valid-JSON rate and correct-tool-sequence rate. Nothing is executed - planning only.
"""
import argparse
import sys

CASES = [
    ("What time is it?", ["get_time"]),
    ("What's today's date?", ["get_date"]),
    ("Calculate 25 times 35", ["calculate"]),
    ("Open YouTube", ["open_website"]),
    ("Open Notepad", ["open_app"]),
    ("Open YouTube and tell me the time", ["open_website", "get_time"]),
    ("Open calculator and then compute 12 * 12", ["open_app", "calculate"]),
    ("What is 2 + 2 and what is today's date?", ["calculate", "get_date"]),
    ("What is time complexity?", []),
    ("Explain how a PID controller works", []),
    ("Tell me a joke", []),
    ("Who are you?", []),
]


def evaluate(planner, cases=CASES):
    from backend.core.agent import PlanError
    rows, valid, correct = [], 0, 0
    for goal, expected in cases:
        try:
            got = [s.tool for s in planner.plan(goal).steps]
            valid += 1
            ok = got == expected
            correct += ok
            rows.append((goal, expected, got, ok))
        except PlanError as e:
            rows.append((goal, expected, f"PLAN ERROR: {e}", False))
    n = len(cases)
    return {"n": n, "valid_rate": valid / n, "correct_rate": correct / n, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="never use a cloud model")
    args = ap.parse_args(argv)
    from backend.core.agent import AgentPlanner, ToolRegistry
    from backend.core.agent.builtin import register_builtin_tools
    from backend.core.llm import AllProvidersFailedError
    from backend.llm import call_llm
    registry = register_builtin_tools(ToolRegistry())
    planner = AgentPlanner(registry, lambda m: call_llm(m, json_mode=True, task="plan",
                                                        allow_cloud=not args.local))
    try:
        res = evaluate(planner)
    except AllProvidersFailedError as e:
        print("No model available:", e)
        return 2
    for goal, exp, got, ok in res["rows"]:
        print(f"{'PASS' if ok else 'FAIL'}  {goal!r}\n      expected={exp}  got={got}")
    print(f"\nvalid plans: {res['valid_rate']:.0%}   correct tool sequences: {res['correct_rate']:.0%}  (n={res['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
