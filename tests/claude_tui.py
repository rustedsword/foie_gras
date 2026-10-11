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

EXAMPLE = Path(__file__).resolve().parent.parent / "example"
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


def prompted(entries):
    return any(e.get("type") == "user" for e in entries)


def attached(entries):
    return [e["attachment"]["displayPath"] for e in entries if (e.get("attachment") or {}).get("type") == "file"]


def forget(sid):
    for f in Path.home().glob(f".claude/projects/*/{sid}.jsonl"):
        shutil.rmtree(f.with_suffix(""), ignore_errors=True)
        f.unlink()


def drive(root, sid, model, typed, done, timeout, args=(), isolated=True, trust=True):
    cmd = [
        "claude", "--model", model, "--strict-mcp-config", "--session-id", sid,
        *(["--setting-sources", "project,local", "--allowedTools=Edit"] if isolated else []), *args,
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env["TERM"] = "xterm-256color"
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(root)
        os.execvpe(cmd[0], cmd, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
    screen, mark, trusted, early, sent = "", 0, False, False, None
    quiet, deadline = time.time(), time.time() + timeout
    try:
        while time.time() < deadline and not done(transcript(sid)):
            if select.select([fd], [], [], 0.3)[0]:
                try:
                    screen += ANSI.sub("", os.read(fd, 1 << 16).decode(errors="replace"))
                    quiet = time.time()
                except OSError:
                    break
            if not trusted and "trustthisfolder" in re.sub(r"\s", "", screen).lower():
                if not trust:
                    break
                time.sleep(1)
                os.write(fd, b"\x1b[B")
                time.sleep(0.5)
                os.write(fd, b"\r")
                trusted, mark = True, len(screen)
            elif sent is None and "❯" in screen[mark:] and time.time() - quiet > 3:
                early = prompted(transcript(sid))
                os.write(fd, typed.encode())
                time.sleep(1)
                os.write(fd, b"\r")
                sent = time.time()
            elif sent and time.time() - sent > 10 and not prompted(transcript(sid)):
                os.write(fd, b"\r")
                sent = time.time()
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
    return screen, early


def task(model, timeout):
    root = Path(tempfile.mkdtemp(prefix="fg-tui-"))
    sid = str(uuid.uuid4())
    try:
        alpha, beta = secrets.token_hex(6), secrets.token_hex(6)
        write(root / "src/alpha.py", f'ALPHA = "{alpha}"\n')
        write(root / "src/beta.py", f'BETA = "{beta}"\n')
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        install_adapter(root)
        guard = hook("PreToolUse", 'echo "blocked by foie_gras test" >&2; exit 2', "|".join(BLOCKED))
        write(root / ".claude/settings.json", json.dumps({"hooks": guard}, indent=2))
        done = lambda t: any("ALPHA=" in r for r in replies(t))
        typed = "/feed " + TASK.format(beta=beta)
        screen, early = drive(root, sid, model, typed, done, timeout, ["--tools=Edit,Bash"])
        entries = transcript(sid)
        context = any(alpha in r for r in replies(entries))
        edit = (root / "src/beta.py").read_text() == 'BETA = "edited"\n'
        return {
            "scenario": "task",
            "auto_started": early,
            "context": context,
            "edit": edit,
            "calls": [b["name"] for b in blocks(entries, "assistant", "tool_use")],
            "reply": (replies(entries) or [""])[-1][-200:],
            "ok": not early and context and edit,
            "screen": screen[-1500:] if not entries else "",
        }
    finally:
        subprocess.run(["claude", "purge", "-y", str(root)], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


def example(model, timeout):
    feed = subprocess.run(
        [EXAMPLE / ".claude/skills/feed/feed.sh"],
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(EXAMPLE)}, capture_output=True, text=True,
    )
    expected = [line[1:].replace("\\ ", " ") for line in feed.stdout.splitlines() if line.startswith("@")]
    sid = str(uuid.uuid4())
    try:
        typed = "/feed Reply with Ready. and nothing else."
        screen, early = drive(EXAMPLE, sid, model, typed, replies, timeout, isolated=False, trust=False)
        entries = transcript(sid)
        files = attached(entries)
        return {
            "scenario": "example",
            "auto_started": early,
            "expected": expected,
            "files": files,
            "reply": (replies(entries) or [""])[-1][:200],
            "ok": not early and sorted(files) == sorted(expected) and any("Ready" in r for r in replies(entries)),
            "screen": screen[-1500:] if not entries else "",
        }
    finally:
        forget(sid)


SCENARIOS = {f.__name__: f for f in [task, example]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", choices=list(SCENARIOS))
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--timeout", type=int, default=240)
    a = ap.parse_args()
    results = [SCENARIOS[s](a.model, a.timeout) for s in a.scenarios or ["task"]]
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
