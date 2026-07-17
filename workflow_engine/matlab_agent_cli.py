import argparse
import json
import sys
from pathlib import Path

from workflow_engine.matlab_agent import MatlabAgent
from workflow_engine.matlab_agent_mcp import McpServer


def parser():
    root = argparse.ArgumentParser(prog="matlab-agent")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--refresh", action="store_true")
    request = commands.add_parser("request")
    request.add_argument("source", help="JSON request file or - for stdin")
    commands.add_parser("mcp")
    return root


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "mcp":
            McpServer().serve()
            return 0
        agent = MatlabAgent()
        try:
            if arguments.command == "doctor":
                result = agent.doctor(arguments.refresh)
            else:
                text = sys.stdin.read() if arguments.source == "-" else Path(arguments.source).read_text(encoding="utf-8-sig")
                result = agent.execute(json.loads(text))
        finally:
            agent.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"ready", "succeeded"} else 1
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
