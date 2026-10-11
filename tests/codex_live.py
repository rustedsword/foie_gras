#!/usr/bin/env python3
"""Exercise the Codex prompt hook with a real model; uses your Codex account."""

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile

from codex import inline_hook, install_hook, write


def run(model, strict, keep):
    root = Path(tempfile.mkdtemp(prefix="fg-codex-live-"))
    try:
        alpha, beta = secrets.token_hex(12), secrets.token_hex(12)
        write(root / "src/alpha.py", f'ALPHA = "{alpha}"\n')
        write(root / "src/beta.py", f'BETA = "{beta}"\n')
        write(root / ".foie_gras/default", "src/**/*.py\n")
        handler = install_hook(root)
        audit = root / "audit.py"
        write(audit, (
            "import json, pathlib, sys\n"
            "event = json.load(sys.stdin)\n"
            "root = pathlib.Path(__file__).parent\n"
            "with (root / 'tool-calls.jsonl').open('a') as log:\n"
            "    log.write(json.dumps(event) + '\\n')\n"
            f"if {strict!r} and event.get('tool_name') not in ('apply_patch', 'exec', 'wait'):\n"
            "    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', "
            "'permissionDecision': 'deny', 'permissionDecisionReason': "
            "'File-reading tools are blocked by the foie_gras integration test. Use the supplied snapshots and apply_patch.'}}))\n"
        ))
        config = {
            "approval_policy": '"never"', "sandbox_mode": '"workspace-write"',
            "web_search": '"disabled"', "features.hooks": "true", "features.plugins": "false",
            "features.apps": "false", "features.multi_agent": "false", "features.multi_agent_v2": "false",
            "features.shell_snapshot": "false",
            "hooks.UserPromptSubmit": inline_hook(handler),
            "hooks.PreToolUse": '[{hooks=[{type="command",command=' + json.dumps(shlex.join([sys.executable, str(audit)])) + '}]}]',
        }
        task = ('In src/beta.py set BETA to "edited". Then tell me the value of ALPHA in src/alpha.py. '
                'End your reply with a line ALPHA=<value>.')
        if strict:
            task += " File-reading tools are blocked in this test; use apply_patch for the edit."
        cmd = ["codex", "exec", "-C", str(root),
               "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
               "--dangerously-bypass-hook-trust", "--json"]
        if model:
            cmd.extend(["--model", model])
        for key, value in config.items():
            cmd.extend(["-c", f"{key}={value}"])
        cmd.append(task)
        temporary = root / "tmp"
        temporary.mkdir()
        result = subprocess.run(cmd, capture_output=True, text=True, input="", timeout=180,
                                env={**os.environ, "TMPDIR": str(temporary), "FOIE_GRAS_LIST": "default"})
        write(root / "events.jsonl", result.stdout)
        write(root / "stderr.txt", result.stderr)
        events = []
        for line in result.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        replies = [event["item"].get("text", "") for event in events
                   if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"]
        calls = root / "tool-calls.jsonl"
        tools = [json.loads(line).get("tool_name") for line in calls.read_text().splitlines()] if calls.exists() else []
        edit = (root / "src/beta.py").read_text() == 'BETA = "edited"\n'
        supplied_context_used = any(f"ALPHA={alpha}" in reply for reply in replies)
        guarded_edit = "apply_patch" in tools and set(tools) <= {"apply_patch", "exec", "wait"}
        row = {"strict": strict, "edit": edit, "context": supplied_context_used, "tools": tools,
               "ok": result.returncode == 0 and edit and supplied_context_used and (not strict or guarded_edit)}
        if not row["ok"]:
            row["error"] = result.stderr[-1000:]
            row["reply"] = "\n".join(replies)[-1000:]
        if keep:
            row["directory"] = str(root)
        return row
    finally:
        if not keep:
            shutil.rmtree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Default: the Codex CLI default model")
    parser.add_argument("--strict", action="store_true", help="Block file-reading tools")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    row = run(args.model, args.strict, args.keep)
    print(json.dumps(row), flush=True)
    raise SystemExit(0 if row["ok"] else 1)


if __name__ == "__main__":
    main()
