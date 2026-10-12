#!/usr/bin/env python3
"""Inspect real opencode requests for feed: against a local mock provider; no model inference."""

import argparse
import fcntl
import http.server
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TASK = 'Rename ALPHA to OMEGA in Bob\'s `alpha.py` and say "done"'
ALPHA = 'ALPHA = "first"\n'
BETA = 'BETA = "second"\n'
ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>78]|\x1bP[^\x1b]*\x1b\\")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Provider(http.server.ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests = []


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, body, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(b'{"object": "list", "data": []}', "application/json")

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(request)
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        chunks = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "MOCK_OK"}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage},
        ]
        body = "".join(f"data: {json.dumps({'id': 'mock', 'object': 'chat.completion.chunk', 'model': 'probe', **c})}\n\n"
                       for c in chunks)
        self.reply((body + "data: [DONE]\n\n").encode(), "text/event-stream")


def environment(base, port):
    # Your config, plugins, MCP servers, sessions and background service stay out of it.
    home = base / "home"
    config = {"model": "mock/probe", "provider": {"mock": {
        "npm": "@ai-sdk/openai-compatible", "name": "Mock",
        "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "mock"},
        "models": {"probe": {"name": "Probe", "limit": {"context": 1000000, "output": 8192}}},
    }}}
    (base / "tmp").mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(base / "tmp"),
        "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local/state"),
        "OPENCODE_CONFIG_CONTENT": json.dumps(config),
        "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1",
    }


def run(root, env, *message, stdin="", args=()):
    command = ["opencode", "run", "--standalone", "--format", "json", *args, *message]
    result = subprocess.run(command, cwd=root, env=env, input=stdin, capture_output=True, text=True, timeout=120)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    return {"events": events, "errors": [e["error"]["message"] for e in events if e.get("type") == "error"]}


def drive(root, env, typed, done, timeout=90):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(root)
        os.execvpe("opencode", ["opencode", "--standalone"], {**env, "TERM": "xterm-256color"})
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
    screen, sent, early, quiet, deadline = b"", False, False, time.time(), time.time() + timeout
    try:
        while time.time() < deadline and not (sent and done(ANSI.sub("", screen.decode(errors="replace")))):
            if select.select([fd], [], [], 0.2)[0]:
                try:
                    data = os.read(fd, 1 << 16)
                except OSError:
                    break
                screen, quiet = screen + data, time.time()
                if b"\x1b[6n" in data:
                    os.write(fd, b"\x1b[1;1R")
            if not sent and screen and time.time() - quiet > 2:
                early = bool(done.provider.requests)
                os.write(fd, b"\x1b[200~" + typed.encode() + b"\x1b[201~")
                time.sleep(0.3)
                os.write(fd, b"\r")
                sent = True
    finally:
        for key in (b"\x03", b"\x03"):
            try:
                os.write(fd, key)
                time.sleep(0.5)
            except OSError:
                pass
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
        os.close(fd)
    return ANSI.sub("", screen.decode(errors="replace")), early


def fed(request):
    """Each user message as the model got it: its text, then each file the plugin shows as read, with its contents.

    Contents are None unless the result reads like the read tool's, starting "Read file <path>, lines 1-<n>".
    """
    rows, reads = [], {}
    for message in request["messages"]:
        content = message.get("content")
        if message["role"] == "user":
            rows.append([content if isinstance(content, str) else "".join(p.get("text", "") for p in content), []])
        for call in message.get("tool_calls") or []:
            if call["id"].startswith("fg_") and call["function"]["name"] == "read":
                reads[call["id"]] = json.loads(call["function"]["arguments"])["path"]
        if message["role"] == "tool" and message["tool_call_id"] in reads:
            name = reads[message["tool_call_id"]]
            header, *lines = content.split("\n")
            text = "".join(line.split(": ", 1)[1] + "\n" for line in lines)
            rows[-1][1].append([name, text if header == f"Read file {name}, lines 1-{len(lines)}" else None])
    return rows


def model_view(api):
    """The agent's last request (title requests carry no tools) and whether a feed: prefix reached any request."""
    turns = [r for r in api.requests if r.get("tools")]
    leaked = any(re.search(r"\bfeed:", json.dumps(r["messages"])) for r in api.requests)
    return {"requests": len(turns), "fed": fed(turns[-1]) if turns else None, "leaked": leaked}


def check(scenario, root, env, api):
    alpha, beta = ["src/alpha.py", ALPHA], ["src/beta.py", BETA]
    if scenario in ("default", "named", "indented", "stdin", "spaces"):
        prompt, files = f"feed: {TASK}", [alpha]
        if scenario == "named":
            prompt, files = f"feed:pair {TASK}", [alpha, beta]
        if scenario == "indented":
            prompt = f"  feed: {TASK}"
        if scenario == "spaces":
            write(root / "src/b c.py", "SPACED = 1\n")
            write(root / ".foie_gras/default", "src/alpha.py\nsrc/b c.py\n")
            files = [alpha, ["src/b c.py", "SPACED = 1\n"]]
        out = run(root, env, stdin=prompt) if scenario == "stdin" else run(root, env, prompt)
        view = model_view(api)
        return {**view, **out, "events": None, "ok": view["requests"] == 1 and view["fed"] == [[TASK, files]]
                and not view["leaked"] and not out["errors"]}
    if scenario in ("piped", "arguments"):
        # `opencode run` quotes each argument that contains spaces and appends piped input on a new line.
        if scenario == "piped":
            out, task = run(root, env, f"feed:pair {TASK}", stdin="DIFF_LINE\n"), f"{TASK}\nDIFF_LINE\n"
        else:
            out, task = run(root, env, "feed:pair Rename ALPHA", "to OMEGA"), 'Rename ALPHA "to OMEGA"'
        view = model_view(api)
        return {**view, **out, "events": None, "ok": view["fed"] == [[task, [alpha, beta]]] and not view["leaked"]}
    if scenario == "large":
        # Past Claude Code's Read limits: 256 KB and 25k tokens.
        sizes = {"big.py": 1000, "huge.py": 2000}
        files = [[f"src/{name}", "".join(f'{name[:-3].upper()}_{i} = "{"x" * 120}"\n' for i in range(count))]
                 for name, count in sizes.items()]
        for name, text in files:
            write(root / name, text)
        write(root / ".foie_gras/default", "".join(f"{name}\n" for name, _ in files))
        out = run(root, env, f"feed: {TASK}")
        view = model_view(api)
        return {"requests": view["requests"], "errors": out["errors"], "ok": view["fed"] == [[TASK, files]]}
    if scenario == "plain":
        prompt = "feed the parser its input"
        out = run(root, env, stdin=prompt)
        view = model_view(api)
        return {**view, "errors": out["errors"], "ok": view["fed"] == [[prompt, []]] and not out["errors"]}
    if scenario in ("alone", "missing", "option"):
        hooks = (root / ".codex/hooks.json").read_text()
        if scenario == "missing":
            write(root / ".foie_gras/default", "src/alpha.py\nsrc/missing.py\n")
        prompt = {"alone": "feed", "missing": f"feed: {TASK}", "option": f"feed:--install {TASK}"}[scenario]
        expected = {"alone": "put your task after feed:", "missing": "No files matched 'src/missing.py'",
                    "option": ".foie_gras/--install'"}[scenario]
        out = run(root, env, prompt)
        kept = (root / ".codex/hooks.json").read_text() == hooks
        return {"requests": len(api.requests), "errors": out["errors"],
                "ok": not api.requests and any(expected in e for e in out["errors"]) and kept}
    if scenario == "resume":
        first = run(root, env, f"feed: {TASK}")
        session = next(e["sessionID"] for e in first["events"] if e.get("sessionID"))
        later = run(root, env, "Continue", args=["--session", session])
        view = model_view(api)
        return {**view, "errors": first["errors"] + later["errors"],
                "ok": view["requests"] == 2 and view["fed"] == [[TASK, [alpha]], ["Continue", []]]}
    if scenario == "interactive":
        done = lambda screen: any(r.get("tools") for r in api.requests) and "MOCK_OK" in screen
        done.provider = api
        screen, early = drive(root, env, f"feed:pair {TASK}", done)
        view = model_view(api)
        return {**view, "early": early, "ok": not early and view["fed"] == [[TASK, [alpha, beta]]] and not view["leaked"],
                "screen": None if view["requests"] else screen[-1500:]}
    if scenario == "example":
        example = REPO / "example"
        out = run(example, env, f"feed:export {TASK}")
        view = model_view(api)
        names = [name for name, _ in view["fed"][0][1]] if view["fed"] else None
        return {"requests": view["requests"], "files": names, "errors": out["errors"],
                "ok": names == ["todo/export.py", "todo/models.py", "todo/store.py"]}
    raise ValueError(scenario)


def scenario_run(scenario, keep):
    base = Path(tempfile.mkdtemp(prefix=f"fg-opencode-{scenario}-"))
    root = base / "repo"
    api = Provider()
    worker = threading.Thread(target=api.serve_forever, daemon=True)
    worker.start()
    try:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        write(root / "src/alpha.py", ALPHA)
        write(root / "src/beta.py", BETA)
        subprocess.run([str(REPO / "foie-gras"), str(root)], capture_output=True, text=True, check=True)
        write(root / ".foie_gras/default", "src/alpha.py\n")
        write(root / ".foie_gras/pair", "src/alpha.py\nsrc/beta.py\n")
        row = {"scenario": scenario, **check(scenario, root, environment(base, api.server_port), api)}
        if keep:
            write(base / "requests.json", json.dumps(api.requests, indent=2))
            row["directory"] = str(base)
        return row
    finally:
        api.shutdown()
        api.server_close()
        worker.join()
        if not keep:
            shutil.rmtree(base)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scenarios = ["default", "named", "indented", "stdin", "piped", "arguments", "spaces", "large", "plain", "alone", "missing", "option", "resume",
                 "interactive", "example"]
    parser.add_argument("scenarios", nargs="*", help=", ".join(scenarios) + " (default: all)")
    parser.add_argument("--keep", action="store_true", help="Keep fixtures and captured requests")
    args = parser.parse_args()
    selected = args.scenarios or scenarios
    if set(selected) - set(scenarios):
        parser.error("Unknown scenario")
    if not shutil.which("opencode"):
        parser.error("opencode is not installed")
    subprocess.run(["make", "-s", "-C", str(REPO), "foie-gras"], check=True, capture_output=True)
    print("opencode", subprocess.check_output(["opencode", "--version"], text=True).strip(), flush=True)
    failed = False
    for scenario in selected:
        try:
            row = scenario_run(scenario, args.keep)
        except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as error:
            row = {"scenario": scenario, "ok": False, "error": repr(error)}
        print(json.dumps({k: v for k, v in row.items() if v is not None}), flush=True)
        failed |= not row["ok"]
    raise SystemExit(int(failed))


if __name__ == "__main__":
    main()
