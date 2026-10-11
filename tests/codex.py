#!/usr/bin/env python3
"""Inspect real Codex requests using a local mock provider; no model inference."""

import argparse
import http.server
import json
import os
import secrets
import sys
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "codex/feed.py"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def install_hook(root):
    subprocess.run([sys.executable, str(SCRIPT), "--install", str(root)],
                   capture_output=True, text=True, check=True)
    return json.loads((root / ".codex/hooks.json").read_text())["hooks"]["UserPromptSubmit"][0]["hooks"][0]


def inline_hook(handler):
    return '[{hooks=[{type="command",additionalContextLimit=0,command=' + json.dumps(handler["command"]) + '}]}]'


class Provider(http.server.ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests = []
        self.title_requests = []
        self.errors = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        # Codex may query /models even with an explicitly selected model.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"models": []}')

    def do_POST(self):
        try:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            request = json.loads(body)
            metadata = json.loads(request.get("client_metadata", {}).get("x-codex-turn-metadata", "{}"))
        except (ValueError, UnicodeError) as error:
            self.server.errors.append(str(error))
            self.send_error(400)
            return
        # The TUI generates conversation titles in separate background threads.
        # Keep them separate from the user turns whose preloads we are checking.
        is_title = metadata.get("thread_source") == "thread_title"
        requests = self.server.title_requests if is_title else self.server.requests
        requests.append(request)
        number = len(requests)
        identity = f"{'title' if is_title else 'probe'}_{number}"
        reply = '{"title":"Test task"}' if is_title else f"MOCK_OK_{number}"
        item = {
            "id": f"msg_{identity}", "type": "message", "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": reply, "annotations": []}],
        }
        events = [
            {"type": "response.created", "response": {
                "id": f"resp_{identity}", "status": "in_progress", "output": [],
            }},
            {"type": "response.output_item.added", "output_index": 0,
             "item": {**item, "status": "in_progress", "content": []}},
            {"type": "response.output_text.delta", "item_id": item["id"],
             "output_index": 0, "content_index": 0, "delta": reply},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {
                "id": f"resp_{identity}", "status": "completed", "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }},
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event in events:
            self.wfile.write(
                ("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode()
            )
        self.wfile.flush()


def provider_config(provider):
    return {
        "model": '"fg-probe"',
        "model_provider": '"fg-probe"',
        "model_providers.fg-probe": (
            '{name="fg-probe",'
            f'base_url="http://127.0.0.1:{provider.server_port}/v1",'
            'wire_api="responses",requires_openai_auth=false,'
            'supports_websockets=false,request_max_retries=0,stream_max_retries=0}'
        ),
        "web_search": '"disabled"',
        "approval_policy": '"never"',
        "sandbox_mode": '"read-only"',
        "features.plugins": "false",
        "features.apps": "false",
        "features.multi_agent": "false",
        "features.multi_agent_v2": "false",
        "features.shell_snapshot": "false",
        "features.enable_request_compression": "false",
    }


def run(scenario, keep):
    root = Path(tempfile.mkdtemp(prefix="fg-codex-exec-"))
    provider = Provider()
    worker = threading.Thread(target=provider.serve_forever, daemon=True)
    worker.start()
    try:
        task = "TASK_" + secrets.token_hex(12)
        body = f'ALPHA = "{secrets.token_hex(12)}"\n'
        if scenario == "large":
            body = "# padding\n" * 10000 + body + "# padding\n" * 10000
        write(root / "alpha.py", body)
        write(root / "beta.py", 'BETA = "NAMED_LIST_ONLY"\n')
        write(root / ".foie_gras/default", "alpha.py\n")
        write(root / ".foie_gras/beta", "beta.py\n")
        handler = install_hook(root)
        cmd = ["codex", "exec", "-C", str(root), "--ignore-user-config", "--ephemeral",
               "--skip-git-repo-check", "--json", "--dangerously-bypass-hook-trust"]
        if scenario == "named":
            task = "feed:beta"
        environment = {key: value for key, value in os.environ.items() if key != "FOIE_GRAS_LIST"}
        if scenario in ("selected", "stdin"):
            environment["FOIE_GRAS_LIST"] = "beta"
        config = provider_config(provider)
        # exec's --ignore-user-config also omits the project hook layer. Test the
        # installed handler inline here; the TUI test exercises project discovery.
        config["hooks.UserPromptSubmit"] = inline_hook(handler)
        for key, value in config.items():
            cmd.extend(["-c", f"{key}={value}"])
        cmd.append("-" if scenario == "stdin" else task)
        result = subprocess.run(cmd, input=task if scenario == "stdin" else "", text=True,
                                capture_output=True, timeout=45, env=environment)
        request = provider.requests[0] if provider.requests else {}
        texts = [
            block.get("text", "")
            for item in request.get("input", [])
            for block in item.get("content", [])
            if isinstance(block, dict)
        ]
        inputs = "\n".join(texts)
        full_content = any(body in text for text in texts)
        named_file = 'BETA = "NAMED_LIST_ONLY"\n' in inputs
        selection_hidden = "FOIE_GRAS_LIST" not in inputs and "feed:" not in inputs
        row = {
            "scenario": scenario, "requests": len(provider.requests),
            "full_default_file": full_content, "named_file": named_file,
            "prompt_copies": inputs.count(task),
            "selection_hidden": selection_hidden,
            "ok": (
                result.returncode == 0 and len(provider.requests) == 1 and not provider.errors
                and full_content == (scenario not in ("selected", "stdin"))
                and named_file == (scenario in ("selected", "stdin"))
                and selection_hidden
                and inputs.count(task) == 1 and "MOCK_OK_1" in result.stdout
            ),
        }
        if scenario == "named":
            # A standalone selector loads context locally, without calling the
            # model. The TUI test checks the subsequent task sees these files.
            # exec --json omits the hook's UI notice; check the completed local
            # turn and zero provider requests instead.
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            completed = [event for event in events if event.get("type") == "turn.completed"]
            local_turn = len(completed) == 1 and all(
                completed[0].get("usage", {}).get(key) == 0
                for key in ("input_tokens", "output_tokens")
            )
            row = {
                "scenario": scenario, "requests": len(provider.requests),
                "local_turn_completed": local_turn,
                "ok": (result.returncode == 0 and local_turn and not provider.requests
                       and not provider.title_requests and not provider.errors),
            }
        if keep:
            write(root / "request.json", json.dumps(request, indent=2))
            write(root / "stdout.jsonl", result.stdout)
            write(root / "stderr.txt", result.stderr)
            row["directory"] = str(root)
        if not row["ok"]:
            row["error"] = result.stderr[-1500:]
        return row
    finally:
        provider.shutdown()
        provider.server_close()
        worker.join()
        if not keep:
            shutil.rmtree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="*", help="default, selected, stdin, named, large (default: all)")
    parser.add_argument("--keep", action="store_true", help="Keep fixtures and captured requests")
    args = parser.parse_args()
    selected = args.scenarios or ["default", "selected", "stdin", "named", "large"]
    if set(selected) - {"default", "selected", "stdin", "named", "large"}:
        parser.error("Unknown scenario")
    if not shutil.which("codex"):
        parser.error("Codex CLI is not installed")
    print(subprocess.check_output(["codex", "--version"], text=True).strip(), flush=True)
    failed = False
    for scenario in selected:
        try:
            row = run(scenario, args.keep)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            row = {"scenario": scenario, "ok": False, "error": str(error)}
        print(json.dumps(row), flush=True)
        failed |= not row["ok"]
    raise SystemExit(int(failed))


if __name__ == "__main__":
    main()
