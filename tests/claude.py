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


def install_adapter(root, agent=False):
    shutil.copytree(ADAPTER / "skills/feed", root / ".claude/skills/feed")
    if agent:
        shutil.copytree(ADAPTER / "agents", root / ".claude/agents")
    write(root / ".foie_gras", "# test manifest\nsrc/**/*.py\n")


def adapter_skill(root, task):
    install_adapter(root)
    return {"prompt": "/feed " + task}


def adapter_agent(root, task):
    install_adapter(root, agent=True)
    return {"prompt": task, "settings": {"agent": "foie-gras"}, "deny": ["Agent(foie-gras)"]}


def adapter_agent_flag(root, task):
    install_adapter(root, agent=True)
    return {"prompt": task, "args": ["--agent", "foie-gras"]}


def adapter_large(root, task):
    install_adapter(root)
    alpha = root / "src/alpha.py"
    alpha.write_text("".join(f'V{i} = "{secrets.token_hex(16)}"\n' for i in range(1500)) + alpha.read_text())
    return {"prompt": "/feed " + task}


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
    adapter_skill,
    adapter_agent,
    adapter_agent_flag,
    adapter_large,
    adapter_large_raised,
]}
OPTIONAL = {"adapter_large", "adapter_large_raised"}
STRICT = {
    "baseline": (False, False),
    "claude_md_import": (True, False),
    "claude_md_import_hint": (True, False),
    "session_start_context": (True, False),
    "session_start_initial_message": (True, True),
    "append_system_prompt": (True, False),
    "prompt_mention": (True, True),
    "command_static": (True, True),
    "skill_static": (True, True),
    "resume_fork": (True, False),
    "adapter_skill": (True, True),
    "adapter_agent": (True, True),
    "adapter_agent_flag": (True, True),
    "adapter_large": (False, True),
    "adapter_large_raised": (True, True),
}


def claude(root, model, prompt, args=(), persist=False, env=None):
    cmd = [
        "claude", "-p", "--model", model, "--output-format", "stream-json", "--verbose",
        "--setting-sources", "project,local", "--strict-mcp-config", "--allowedTools=Edit,Write",
        "--max-turns", "6", "--max-budget-usd", "1",
        *([] if persist else ["--no-session-persistence"]), *args,
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
            if block.get("type") == "tool_use":
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


def run(name, model, keep, strict):
    root = Path(tempfile.mkdtemp(prefix=f"fg-{name}-"))
    try:
        alpha, beta = secrets.token_hex(6), secrets.token_hex(6)
        write(root / "src/alpha.py", f'ALPHA = "{alpha}"\n')
        write(root / "src/beta.py", f'BETA = "{beta}"\n')
        write(root / ".foie_gras", "\n".join(FILES) + "\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        spec = MECHANISMS[name](root, TASK.format(beta=beta) if strict else NATURAL_TASK)
        guard = hook("PreToolUse", 'echo "blocked by foie_gras test" >&2; exit 2', "|".join(BLOCKED)) if strict else {}
        settings = {
            "hooks": {**guard, **spec.get("hooks", {})},
            "permissions": {"deny": spec.get("deny", [])},
            **spec.get("settings", {}),
        }
        write(root / ".claude/settings.json", json.dumps(settings, indent=2))
        cost, args = 0, ["--tools=Edit,Bash"] * strict + list(spec.get("args", []))
        if "prime" in spec:
            sid = str(uuid.uuid4())
            events, _ = claude(root, model, spec["prime"], ["--session-id", sid], persist=True)
            cost += analyze(events)["cost"]
            args += ["--resume", sid, "--fork-session"]
        events, stderr = claude(root, model, spec["prompt"], args, persist="prime" in spec, env=spec.get("env"))
        r = analyze(events)
        return {
            "mechanism": name,
            "context": alpha in r["text"],
            "edit": (root / "src/beta.py").read_text() == 'BETA = "edited"\n',
            "reads": sum(c in READS for c in r["calls"]),
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
    print(f"{'mechanism':30} {'context':8} {'edit':6} {'reads':6} {'cost':7} {'verdict':8} error", file=sys.stderr if a.json else sys.stdout)
    for m in a.mechanisms:
        rs = [r for r in rows if r["mechanism"] == m]
        ok = all((r["context"], r["edit"]) == STRICT[m] for r in rs) if a.strict else None
        failed |= ok is False
        err = next((r["edit_errors"][0] if r["edit_errors"] else r["error"] for r in rs if r["edit_errors"] or r["error"]), "")
        print(
            f"{m:30} {sum(r['context'] for r in rs)}/{len(rs):<6} {sum(r['edit'] for r in rs)}/{len(rs):<4} "
            f"{sum(r['reads'] for r in rs) / len(rs):<6.1f} {sum(r['cost'] for r in rs):<7.3f} "
            f"{'' if ok is None else 'PASS' if ok else 'FAIL':8} {err.replace(chr(10), ' ')[:60]}",
            file=sys.stderr if a.json else sys.stdout,
        )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
