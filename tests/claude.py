#!/usr/bin/env python3
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ADAPTER = Path(__file__).resolve().parent.parent / "claude"
FILES = ["src/alpha.py", "src/beta.py"]
READS = {"Read", "Grep", "Glob", "Bash"}
# The Read calls the mod makes; the strict guard lets them through, and they are not counted as rereads.
FED = "toolu_foiegras"
GUARD = ("python3 -c \"import json, sys; fed = json.load(sys.stdin).get('tool_use_id', '').startswith('" + FED + "'); "
         "fed or print('blocked by foie_gras test', file=sys.stderr); sys.exit(0 if fed else 2)\"")
BLOCKED = READS | {"Write", "NotebookEdit", "Agent", "LSP", "Monitor"}
TASK = (
    "Read, Grep, Glob and Bash are blocked in this session. "
    "1) Call the Edit tool once on src/beta.py with old_string `BETA = \"{beta}\"` "
    "and new_string `BETA = \"edited\"`. "
    "2) Then, without any tools, tell me the value of ALPHA in src/alpha.py, "
    "or NOT_IN_CONTEXT if its content is not in your context. "
    "End your reply with a line `ALPHA=<value>`."
)
NATURAL_TASK = (
    "In src/beta.py set BETA to \"edited\". Then tell me the value of ALPHA in src/alpha.py. "
    "End your reply with a line `ALPHA=<value>`."
)
SKILL_HEAD = "---\nname: feed\ndescription: Load the foie_gras file set\ndisable-model-invocation: true\n---\n\n"
MENTIONS = " ".join("@" + f for f in FILES)
MENTION_LINES = "\n".join("@" + f for f in FILES) + "\n"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def hook(event, command, matcher=None):
    entry = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        entry["matcher"] = matcher
    return {event: [entry]}


def session_start_script(root, field, value_expr):
    write(
        root / ".claude/hooks/feed.py",
        "import json, pathlib\n"
        "files = pathlib.Path('.foie_gras').read_text().split()\n"
        "body = '\\n\\n'.join(f'<file path=\"{f}\">\\n{pathlib.Path(f).read_text()}</file>' for f in files)\n"
        f"value = {value_expr}\n"
        f"print(json.dumps({{'hookSpecificOutput': {{'hookEventName': 'SessionStart', '{field}': value}}}}))\n",
    )
    return hook("SessionStart", 'cd "$CLAUDE_PROJECT_DIR" && python3 .claude/hooks/feed.py')


def baseline(root, task):
    return {"prompt": task}


def claude_md_import(root, task):
    write(root / "CLAUDE.md", MENTION_LINES)
    return {"prompt": task}


def claude_md_import_hint(root, task):
    hint = "These files are preloaded with their current contents: use them directly, do not Read them again.\n"
    write(root / "CLAUDE.md", hint + MENTION_LINES)
    return {"prompt": task}


def session_start_context(root, task):
    return {"prompt": task, "hooks": session_start_script(root, "additionalContext", "body")}


def session_start_initial_message(root, task):
    write(root / ".claude/initial.txt", MENTIONS + " " + task)
    hooks = session_start_script(root, "initialUserMessage", "pathlib.Path('.claude/initial.txt').read_text()")
    return {"prompt": None, "hooks": hooks}


def append_system_prompt(root, task):
    body = "\n\n".join(f'<file path="{f}">\n{(root / f).read_text()}</file>' for f in FILES)
    return {"prompt": task, "args": ["--append-system-prompt", body]}


def prompt_mention(root, task):
    return {"prompt": MENTIONS + " " + task}


def command_static(root, task):
    write(root / ".claude/commands/feed.md", MENTION_LINES + "\n$ARGUMENTS\n")
    return {"prompt": "/feed " + task}


def skill_static(root, task):
    write(root / ".claude/skills/feed/SKILL.md", SKILL_HEAD + MENTION_LINES + "\n$ARGUMENTS\n")
    return {"prompt": "/feed " + task}


def install_adapter(root, lists=None):
    shutil.copytree(ADAPTER / "foie-gras", root / ".claude/skills/foie-gras")
    if lists is None:
        write(root / ".foie_gras", "# test manifest\nsrc/**/*.py\n")
    else:
        (root / ".foie_gras").unlink(missing_ok=True)
        for name, body in lists.items():
            write(root / ".foie_gras" / name, body)
    # A throwaway directory is not a trusted workspace, so Claude Code would skip the project's mod.
    return ["--plugin-dir", str(root / ".claude/skills/foie-gras")]


def adapter_feed(root, task):
    return {"prompt": "feed: " + task, "args": install_adapter(root), "tools": "Read,Edit,Bash"}


def adapter_list(root, task):
    args = install_adapter(root, {"default": "src/beta.py\n", "pair": "src/alpha.py\nsrc/beta.py\n"})
    return {"prompt": "feed:pair " + task, "args": args, "tools": "Read,Edit,Bash"}


def adapter_large(root, task):
    spec = adapter_feed(root, task)
    alpha = root / "src/alpha.py"
    alpha.write_text("".join(f'V{i} = "{secrets.token_hex(16)}"\n' for i in range(1500)) + alpha.read_text())
    return spec


def adapter_large_raised(root, task):
    return {**adapter_large(root, task), "env": {"CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS": "100000"}}


def resume_fork(root, task):
    return {"prompt": task, "prime": MENTIONS + " Reply with OK only."}


MECHANISMS = {f.__name__: f for f in [
    baseline,
    claude_md_import,
    claude_md_import_hint,
    session_start_context,
    session_start_initial_message,
    append_system_prompt,
    prompt_mention,
    command_static,
    skill_static,
    resume_fork,
    adapter_feed,
    adapter_list,
    adapter_large,
    adapter_large_raised,
]}
OPTIONAL = {"adapter_large", "adapter_large_raised"}
MARKER = "ALPHA=<value>"
STRICT = {
    "baseline": (False, False, 1),
    "claude_md_import": (True, False, 1),
    "claude_md_import_hint": (True, False, 1),
    "session_start_context": (True, False, 1),
    "session_start_initial_message": (True, True, 1),
    "append_system_prompt": (True, False, 1),
    "prompt_mention": (True, True, 1),
    "command_static": (True, True, 2),
    "skill_static": (True, True, 2),
    "resume_fork": (True, False, 1),
    "adapter_feed": (True, True, 1),
    "adapter_list": (True, True, 1),
    "adapter_large": (False, True, 1),
    "adapter_large_raised": (True, True, 1),
}


def claude(root, model, prompt, args=(), env=None):
    cmd = [
        "claude", "-p", "--model", model, "--output-format", "stream-json", "--verbose",
        "--setting-sources", "project,local", "--strict-mcp-config", "--allowedTools=Edit,Write",
        "--max-turns", "6", "--max-budget-usd", "1",
        *args,
    ]
    if prompt is not None:
        cmd.append(prompt)
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}, **(env or {})}
    p = subprocess.run(cmd, cwd=root, env=env, input="", capture_output=True, text=True, timeout=900)
    events = []
    for line in p.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events, p.stderr


def analyze(events):
    tools, results = {}, {}
    for e in events:
        message = e.get("message")
        for block in (message.get("content") if isinstance(message, dict) else None) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and not block["id"].startswith(FED):
                tools[block["id"]] = block["name"]
            elif block.get("type") == "tool_result" and block.get("is_error"):
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content)
                results[block["tool_use_id"]] = str(content)
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {
        "calls": list(tools.values()),
        "edit_errors": [results[i] for i, n in tools.items() if n == "Edit" and i in results],
        "text": final.get("result") or "",
        "cost": final.get("total_cost_usd") or 0,
        "error": final.get("subtype") if final.get("subtype") != "success" else None,
    }


def copies(events):
    sid = next((e["session_id"] for e in events if e.get("session_id")), None)
    path = next(Path.home().glob(f".claude/projects/*/{sid}.jsonl"), None) if sid else None
    count = 0
    for line in path.read_text().splitlines() if path else []:
        e = json.loads(line)
        content = (e.get("message") or {}).get("content") if e.get("type") == "user" else None
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
        count += (content or "").count(MARKER)
    return count


def run(name, model, keep, strict):
    root = Path(tempfile.mkdtemp(prefix=f"fg-{name}-"))
    try:
        alpha, beta = secrets.token_hex(6), secrets.token_hex(6)
        write(root / "src/alpha.py", f'ALPHA = "{alpha}"\n')
        write(root / "src/beta.py", f'BETA = "{beta}"\n')
        write(root / ".foie_gras", "\n".join(FILES) + "\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        spec = MECHANISMS[name](root, TASK.format(beta=beta) if strict else NATURAL_TASK)
        guard = hook("PreToolUse", GUARD, "|".join(BLOCKED)) if strict else {}
        settings = {
            "hooks": {**guard, **spec.get("hooks", {})},
            **spec.get("settings", {}),
        }
        write(root / ".claude/settings.json", json.dumps(settings, indent=2))
        cost, args = 0, ["--tools=" + spec.get("tools", "Edit,Bash")] * strict + list(spec.get("args", []))
        if "prime" in spec:
            sid = str(uuid.uuid4())
            events, _ = claude(root, model, spec["prime"], ["--session-id", sid])
            cost += analyze(events)["cost"]
            args += ["--resume", sid, "--fork-session"]
        events, stderr = claude(root, model, spec["prompt"], args, env=spec.get("env"))
        r = analyze(events)
        return {
            "mechanism": name,
            "context": alpha in r["text"],
            "edit": (root / "src/beta.py").read_text() == 'BETA = "edited"\n',
            "reads": sum(c in READS for c in r["calls"]),
            "copies": copies(events),
            "calls": r["calls"],
            "edit_errors": r["edit_errors"],
            "error": r["error"] or (stderr.strip()[:300] if not events else None),
            "cost": round(cost + r["cost"], 4),
            "text": r["text"][-300:],
        }
    finally:
        if keep:
            print(f"kept {root}", file=sys.stderr)
        else:
            subprocess.run(["claude", "purge", "-y", str(root)], capture_output=True)
            shutil.rmtree(root, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mechanisms", nargs="*", default=[m for m in MECHANISMS if m not in OPTIONAL])
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    jobs = [m for m in a.mechanisms for _ in range(a.repeat)]
    with ThreadPoolExecutor(min(len(jobs), a.jobs)) as pool:
        rows = list(pool.map(lambda m: run(m, a.model, a.keep, a.strict), jobs))
    if a.json:
        print(json.dumps(rows, indent=2))
    failed = False
    print(f"{'mechanism':30} {'context':8} {'edit':6} {'reads':6} {'copies':7} {'cost':7} {'verdict':8} error", file=sys.stderr if a.json else sys.stdout)
    for m in a.mechanisms:
        rs = [r for r in rows if r["mechanism"] == m]
        ok = all((r["context"], r["edit"], r["copies"]) == STRICT[m] for r in rs) if a.strict else None
        failed |= ok is False
        err = next((r["edit_errors"][0] if r["edit_errors"] else r["error"] for r in rs if r["edit_errors"] or r["error"]), "")
        print(
            f"{m:30} {sum(r['context'] for r in rs)}/{len(rs):<6} {sum(r['edit'] for r in rs)}/{len(rs):<4} "
            f"{sum(r['reads'] for r in rs) / len(rs):<6.1f} {'/'.join(sorted({str(r['copies']) for r in rs})):<7} "
            f"{sum(r['cost'] for r in rs):<7.3f} "
            f"{'' if ok is None else 'PASS' if ok else 'FAIL':8} {err.replace(chr(10), ' ')[:60]}",
            file=sys.stderr if a.json else sys.stdout,
        )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
