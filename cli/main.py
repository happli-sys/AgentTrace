"""
AgentTrace CLI

Commands:
  agenttrace report  <json_file>
  agenttrace compare <json1> <json2> ...
  agenttrace regression <json> --baseline <name> [--save]
  agenttrace hook-server [--port 7755] [--store-dir .agenttrace]
  agenttrace inject-hooks [--port 7755]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agenttrace.metrics.engine import EvalResult
from agenttrace.metrics.comparison import compare
from agenttrace.metrics.regression import RegressionTracker
from agenttrace.reporters.json_reporter import JSONReporter


def _load_result(path: str) -> EvalResult:
    with open(path) as f:
        data = json.load(f)
    return EvalResult(**{k: v for k, v in data.items() if k != "tool_stats"})


def cmd_report(args):
    print(_load_result(args.file).summary())


def cmd_compare(args):
    print(compare([_load_result(p) for p in args.files]))


def cmd_regression(args):
    tracker = RegressionTracker(store_dir=args.store_dir)
    result  = _load_result(args.file)
    if args.save:
        tracker.save_baseline(result, args.baseline)
        return
    report = tracker.compare(result, args.baseline)
    print(report.summary())
    if not report.passed:
        sys.exit(1)


def cmd_hook_server(args):
    from agenttrace.integrations.claude_code.hook_server import HookServer
    srv = HookServer(port=args.port, store_dir=args.store_dir)
    srv.start_background()
    srv.wait()


def cmd_inject_hooks(args):
    from agenttrace.integrations.claude_code.hook_server import inject_hooks
    inject_hooks(port=args.port, settings_path=args.settings)


def main():
    parser = argparse.ArgumentParser(
        prog="agenttrace",
        description="AgentTrace — Objective AI Agent evaluation"
    )
    sub = parser.add_subparsers(dest="command")

    # report
    p = sub.add_parser("report", help="Print a saved evaluation report")
    p.add_argument("file")

    # compare
    p = sub.add_parser("compare", help="Compare multiple report files")
    p.add_argument("files", nargs="+")

    # regression
    p = sub.add_parser("regression", help="Regression check against baseline")
    p.add_argument("file")
    p.add_argument("--baseline", required=True)
    p.add_argument("--save", action="store_true")
    p.add_argument("--store-dir", default=".agenttrace")

    # hook-server
    p = sub.add_parser("hook-server", help="Start hook server for Claude Code monitoring")
    p.add_argument("--port", type=int, default=7755)
    p.add_argument("--store-dir", default=".agenttrace")

    # inject-hooks
    p = sub.add_parser("inject-hooks",
                        help="Auto-inject AgentTrace hooks into ~/.claude/settings.json")
    p.add_argument("--port", type=int, default=7755)
    p.add_argument("--settings", default=None,
                   help="Path to settings.json (default: ~/.claude/settings.json)")

    args = parser.parse_args()
    {
        "report":        cmd_report,
        "compare":       cmd_compare,
        "regression":    cmd_regression,
        "hook-server":   cmd_hook_server,
        "inject-hooks":  cmd_inject_hooks,
    }.get(args.command, lambda _: parser.print_help())(args)


if __name__ == "__main__":
    main()
