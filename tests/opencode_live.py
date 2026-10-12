#!/usr/bin/env python3
"""Exercise the opencode plugin with real models; free models need no account."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

from opencode_free_models import isolated


REPO = Path(__file__).resolve().parents[1]
READS = {"read", "grep", "glob", "shell"}
# Denies the calls but keeps the tools listed: opencode's free tier refuses a request whose tool list was cut.
GUARD = """export default {
  id: 'foie-gras-live-guard',
  setup: async ctx => {
    await ctx.permission.hook('evaluate', event => {
      if (!%s.includes(event.action)) return
      event.effect = 'deny'
      event.message = 'File-reading tools are blocked in this test.'
    })
  },
}
""" % json.dumps(sorted(READS))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(model, strict, yours, keep):
    base = Path(tempfile.mkdtemp(prefix="fg-opencode-live-"))
    root = base / "repo"
    try:
        alpha, beta = secrets.token_hex(12), secrets.token_hex(12)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        write(root / "src/alpha.py", f'ALPHA = "{alpha}"\n')
        write(root / "src/beta.py", f'BETA = "{beta}"\n')
        subprocess.run([str(REPO / "foie-gras"), str(root)], check=True, capture_output=True)
        write(root / ".foie_gras/default", "src/**/*.py\n")
        task = ('In src/beta.py set BETA to "edited". Then tell me the value of ALPHA in src/alpha.py. '
                'End your reply with a line ALPHA=<value>.')
        environment = dict(os.environ) if yours else isolated(base)
        if strict:
            task += " File-reading tools are blocked in this test; use the edit tool for the edit."
            write(root / ".opencode/plugins/guard.ts", GUARD)
        command = ["opencode", "run", "--standalone", "--auto", "--format", "json", "--model", model]
        result = subprocess.run(command, cwd=root, env=environment, input=f"feed: {task}", capture_output=True,
                                text=True, timeout=600)
        write(base / "events.jsonl", result.stdout)
        write(base / "stderr.txt", result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        parts = [event.get("part", {}) for event in events]
        calls = [part for part in parts if part.get("type") == "tool"]
        # Each call with what it touched, as "read src/alpha.py".
        tools = [" ".join([call["tool"], *(str(value) for key, value in call["state"].get("input", {}).items()
                                           if key in ("path", "pattern", "command"))]).replace(f"{root}/", "")
                 for call in calls]
        read = any(call["tool"] in READS and call["state"].get("status") == "completed" for call in calls)
        replies = [part.get("text", "") for part in parts if part.get("type") == "text"]
        edit = (root / "src/beta.py").read_text() == 'BETA = "edited"\n'
        context = any(alpha in reply for reply in replies)
        row = {"model": model, "strict": strict, "edit": edit, "context": context, "tools": tools,
               "ok": result.returncode == 0 and edit and context and not (strict and read)}
        if not row["ok"]:
            row["errors"] = [event["error"]["message"] for event in events if event.get("type") == "error"]
            row["reply"] = "\n".join(replies)[-500:]
        if keep:
            row["directory"] = str(base)
        return row
    except subprocess.TimeoutExpired:
        return {"model": model, "strict": strict, "ok": False, "errors": ["timed out"]}
    finally:
        if not keep:
            shutil.rmtree(base)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", nargs="+", action="extend", required=True,
                        help="provider/model, one or more; see opencode_free_models.py")
    parser.add_argument("--strict", action="store_true", help="Deny read, grep, glob and shell calls")
    parser.add_argument("--your-config", action="store_true",
                        help="Use your opencode config and account, for models that need one")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    subprocess.run(["make", "-s", "-C", str(REPO), "foie-gras"], check=True, capture_output=True)
    with ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(lambda model: run(model, args.strict, args.your_config, args.keep), args.model))
    for row in rows:
        print(json.dumps(row), flush=True)
    raise SystemExit(0 if all(row["ok"] for row in rows) else 1)


if __name__ == "__main__":
    main()
