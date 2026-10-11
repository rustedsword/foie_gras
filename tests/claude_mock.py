#!/usr/bin/env python3
"""Inspect real Claude Code requests for feed: against a local mock API; no model inference."""

import argparse
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

import claude_tui as tui


REPO = Path(__file__).resolve().parents[1]
MOD = ".claude/skills/foie-gras"
TASK = "Rename ALPHA to OMEGA in Bob's `alpha.py`"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Api(http.server.ThreadingHTTPServer):
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
        self.reply(b"{}", "application/json")

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "count_tokens" in self.path:
            return self.reply(b'{"input_tokens": 1}', "application/json")
        self.server.requests.append(request)
        usage = {"input_tokens": 1, "output_tokens": 1}
        message = {"id": "msg_mock", "type": "message", "role": "assistant", "model": request.get("model", "mock"),
                   "content": [], "stop_reason": None, "stop_sequence": None, "usage": usage}
        if not request.get("stream"):
            message.update(content=[{"type": "text", "text": "Ready."}], stop_reason="end_turn")
            return self.reply(json.dumps(message).encode(), "application/json")
        events = [
            {"type": "message_start", "message": message},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Ready."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": usage},
            {"type": "message_stop"},
        ]
        self.reply("".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode(), "text/event-stream")


def printed(root, prompt, args=()):
    # A throwaway directory is not a trusted workspace, so Claude Code would skip the project's mod.
    command = ["claude", "-p", "--model", "haiku", "--setting-sources", "project,local", "--strict-mcp-config",
               "--plugin-dir", str(root / MOD), *args, prompt]
    environment = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    result = subprocess.run(command, cwd=root, env=environment, input="", capture_output=True, text=True, timeout=120)
    return result.stdout + result.stderr


def model_view(request):
    """What Claude got: the user's text, the Read calls the mod made, and their results."""
    texts, reads, results = [], [], {}
    for message in request["messages"]:
        content = message["content"]
        for b in [{"type": "text", "text": content}] if isinstance(content, str) else content:
            if b["type"] == "text" and message["role"] == "user" and not b["text"].startswith("<system-reminder>"):
                texts.append(b["text"].strip())
            elif b["type"] == "tool_use" and b["id"].startswith("toolu_foiegras"):
                reads.append((b["id"], Path(b["input"]["file_path"]).name))
            elif b["type"] == "tool_result":
                content = b["content"]
                results[b["tool_use_id"]] = content if isinstance(content, str) else " ".join(c.get("text", "") for c in content)
    return {"texts": texts, "reads": [name for _, name in reads],
            "results": all(results.get(i, "").startswith("1\t") for i, _ in reads)}


def fed(api, prompt, files):
    """The request carrying the prompt shows just the prompt, then Read calls for the files and their results."""
    # Requests without tools are Claude Code's own, such as the session title.
    request = next((r for r in api.requests if r.get("tools") and prompt in json.dumps(r["messages"])), None)
    if request is None:
        return {"ok": False, "requests": len(api.requests)}
    view = model_view(request)
    return {**view, "ok": view["texts"] == [prompt] and view["reads"] == files and view["results"]}


def check(scenario, root, api):
    if scenario == "default":
        printed(root, f"feed: {TASK}")
        return fed(api, TASK, ["alpha.py"])
    if scenario == "named":
        printed(root, f"feed:pair {TASK}")
        return fed(api, TASK, ["alpha.py", "beta.py"])
    if scenario == "spaces":
        write(root / "src/b c.py", "SPACED = 1\n")
        write(root / ".foie_gras/default", "src/alpha.py\nsrc/b c.py\n")
        printed(root, f"feed: {TASK}")
        return fed(api, TASK, ["alpha.py", "b c.py"])
    if scenario == "plain":
        prompt = "feed the parser its input"
        printed(root, prompt)
        view = model_view(api.requests[-1])
        return {**view, "ok": view["texts"] == [prompt] and not view["reads"]}
    if scenario in ("alone", "missing"):
        if scenario == "missing":
            write(root / ".foie_gras/default", "src/alpha.py\nsrc/missing.py\n")
        output = printed(root, "feed" if scenario == "alone" else f"feed: {TASK}")
        expected = "put your task after feed:" if scenario == "alone" else "No files matched 'src/missing.py'"
        return {"requests": len(api.requests), "ok": not api.requests and expected in output}
    if scenario == "option":
        hooks = (root / ".codex/hooks.json").read_text()
        output = printed(root, f"feed:--install {TASK}")
        kept = (root / ".codex/hooks.json").read_text() == hooks
        return {"requests": len(api.requests), "ok": not api.requests and ".foie_gras/--install'" in output and kept}
    if scenario == "resume":
        sid = str(uuid.uuid4())
        printed(root, f"feed: {TASK}", ["--session-id", sid])
        printed(root, "Continue", ["--resume", sid])
        later = model_view(api.requests[-1])
        return {**later, "ok": len(api.requests) == 2 and later["texts"] == [TASK, "Continue"] and later["reads"] == ["alpha.py"]}
    if scenario == "interactive":
        sid = str(uuid.uuid4())
        screen, early = tui.drive(root, sid, "haiku", f"feed: {TASK}", tui.replies, 90)
        row = fed(api, TASK, ["alpha.py"])
        return {**row, "ok": not early and row["ok"]}
    raise ValueError(scenario)


def run(scenario, keep):
    root = Path(tempfile.mkdtemp(prefix=f"fg-claude-{scenario}-"))
    api = Api()
    worker = threading.Thread(target=api.serve_forever, daemon=True)
    worker.start()
    os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{api.server_port}"
    try:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        write(root / "src/alpha.py", 'ALPHA = "first"\n')
        write(root / "src/beta.py", 'BETA = "second"\n')
        write(root / ".foie_gras/default", "src/alpha.py\n")
        write(root / ".foie_gras/pair", "src/alpha.py\nsrc/beta.py\n")
        subprocess.run([str(REPO / "foie-gras"), str(root)], capture_output=True, text=True, check=True)
        row = {"scenario": scenario, **check(scenario, root, api)}
        if keep:
            write(root / "requests.json", json.dumps(api.requests, indent=2))
            row["directory"] = str(root)
        return row
    finally:
        api.shutdown()
        api.server_close()
        worker.join()
        subprocess.run(["claude", "purge", "-y", str(root)], capture_output=True)
        if not keep:
            shutil.rmtree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scenarios = ["default", "named", "spaces", "plain", "alone", "missing", "option", "resume", "interactive"]
    parser.add_argument("scenarios", nargs="*", help=", ".join(scenarios) + " (default: all)")
    parser.add_argument("--keep", action="store_true", help="Keep fixtures and captured requests")
    args = parser.parse_args()
    selected = args.scenarios or scenarios
    if set(selected) - set(scenarios):
        parser.error("Unknown scenario")
    if not shutil.which("claude"):
        parser.error("Claude Code is not installed")
    # A token instead of an API key: Claude Code asks before using an API key from the environment.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "mock"
    subprocess.run(["make", "-s", "-C", str(REPO), "foie-gras"], check=True, capture_output=True)
    print(subprocess.check_output(["claude", "--version"], text=True).strip(), flush=True)
    failed = False
    for scenario in selected:
        try:
            row = run(scenario, args.keep)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            row = {"scenario": scenario, "ok": False, "error": repr(error)}
        print(json.dumps(row), flush=True)
        failed |= not row["ok"]
    raise SystemExit(int(failed))


if __name__ == "__main__":
    main()
