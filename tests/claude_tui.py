#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import pty
import re
import secrets
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import uuid
from pathlib import Path

from claude import BLOCKED, TASK, hook, install_adapter, write

ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>78]")


def transcript(sid):
    found = list(Path.home().glob(f".claude/projects/*/{sid}.jsonl"))
    entries = []
    for line in found[0].read_text().splitlines() if found else []:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def blocks(entries, role, kind):
    for e in entries:
        content = (e.get("message") or {}).get("content") if e.get("type") == role else None
        if isinstance(content, str) and kind == "text":
            yield {"type": "text", "text": content}
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == kind:
                yield b


def replies(entries):
    return [b["text"] for b in blocks(entries, "assistant", "text")]


def drive(root, sid, model, prompt, done, timeout, args=()):
    cmd = [
        "claude", "--model", model, "--setting-sources", "project,local", "--strict-mcp-config",
        "--allowedTools=Edit", "--session-id", sid, *args, *([prompt] if prompt else []),
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env["TERM"] = "xterm-256color"
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(root)
        os.execvpe(cmd[0], cmd, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
    screen, trusted, deadline = "", False, time.time() + timeout
    try:
        while time.time() < deadline and not done(transcript(sid)):
            if select.select([fd], [], [], 0.5)[0]:
                try:
                    screen += ANSI.sub("", os.read(fd, 1 << 16).decode(errors="replace"))
                except OSError:
                    break
            if not trusted and "trustthisfolder" in re.sub(r"\s", "", screen).lower():
                time.sleep(1)
                os.write(fd, b"\x1b[B")
                time.sleep(0.5)
                os.write(fd, b"\r")
                trusted = True
    finally:
        for key in (b"\x03", b"\x03"):
            try:
                os.write(fd, key)
                time.sleep(0.7)
            except OSError:
                pass
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
        os.close(fd)
    return screen


def fixture(strict):
    root = Path(tempfile.mkdtemp(prefix="fg-tui-"))
    alpha, beta = secrets.token_hex(6), secrets.token_hex(6)
    write(root / "src/alpha.py", f'ALPHA = "{alpha}"\n')
    write(root / "src/beta.py", f'BETA = "{beta}"\n')
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    install_adapter(root, agent=True)
    guard = hook("PreToolUse", 'echo "blocked by foie_gras test" >&2; exit 2', "|".join(BLOCKED)) if strict else {}
    settings = {"agent": "foie-gras", "permissions": {"deny": ["Agent(foie-gras)"]}, "hooks": guard}
    write(root / ".claude/settings.json", json.dumps(settings, indent=2))
    return root, alpha, beta


def bootstrap(model, timeout):
    root, alpha, _ = fixture(strict=False)
    sid = str(uuid.uuid4())
    try:
        screen = drive(root, sid, model, None, lambda t: replies(t), timeout)
        entries = transcript(sid)
        files = [e["attachment"]["filename"] for e in entries if (e.get("attachment") or {}).get("type") == "file"]
        return {
            "scenario": "bootstrap",
            "feed_ran": any("<command-name>/feed</command-name>" in t for t in (b["text"] for b in blocks(entries, "user", "text"))),
            "files": [Path(f).name for f in files],
            "reply": (replies(entries) or [""])[-1][:200],
            "ok": len(files) == 2 and any("Ready" in r for r in replies(entries)),
            "screen": screen[-1500:] if not entries else "",
        }
    finally:
        subprocess.run(["claude", "purge", "-y", str(root)], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


def task(model, timeout):
    root, alpha, beta = fixture(strict=True)
    sid = str(uuid.uuid4())
    try:
        prompt = TASK.format(beta=beta)
        done = lambda t: any("ALPHA=" in r for r in replies(t))
        screen = drive(root, sid, model, prompt, done, timeout, ["--tools=Edit,Bash"])
        entries = transcript(sid)
        calls = [b["name"] for b in blocks(entries, "assistant", "tool_use")]
        context = any(alpha in r for r in replies(entries))
        edit = (root / "src/beta.py").read_text() == 'BETA = "edited"\n'
        return {
            "scenario": "task",
            "context": context,
            "edit": edit,
            "calls": calls,
            "reply": (replies(entries) or [""])[-1][-200:],
            "ok": context and edit,
            "screen": screen[-1500:] if not entries else "",
        }
    finally:
        subprocess.run(["claude", "purge", "-y", str(root)], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--timeout", type=int, default=240)
    a = ap.parse_args()
    results = [bootstrap(a.model, a.timeout), task(a.model, a.timeout)]
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
