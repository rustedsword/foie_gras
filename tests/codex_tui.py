#!/usr/bin/env python3
"""Review the hook and explicitly load files in a real Codex TUI (isolated, Linux)."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import secrets
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time

from codex import Provider, install_hook, provider_config, write


def run(timeout, keep, scenario="default"):
    root = Path(tempfile.mkdtemp(prefix="fg-codex-tui-"))
    state = root / "codex-state"
    provider = Provider()
    worker = threading.Thread(target=provider.serve_forever, daemon=True)
    worker.start()
    process = None
    master = None
    try:
        marker, task = "FILE_" + secrets.token_hex(12), "TASK_" + secrets.token_hex(12)
        body = f'ALPHA = "{marker}"\n'
        if scenario == "large":
            body = "# padding\n" * 6000 + body + "# padding\n" * 6000
        write(root / "alpha.py", body)
        write(root / ".foie_gras/default", "alpha.py\n")
        write(root / ".foie_gras/beta", "beta.py\n")
        named_body = 'BETA = "NAMED_LIST_ONLY"\n'
        write(root / "beta.py", named_body)
        install_hook(root)
        config = "\n".join(f"{key} = {value}" for key, value in provider_config(provider).items())
        config += f'\n[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n'
        write(state / "config.toml", config)
        # Mask the Codex state directory in a mount namespace, leaving the user's
        # environment and actual config, credentials, hooks, and sessions alone.
        state_location = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
        cmd = [
            "bwrap", "--die-with-parent", "--unshare-pid", "--ro-bind", "/", "/",
            "--bind", str(root), str(root), "--bind", str(state), str(state_location),
            "--dev-bind", "/dev", "/dev", "--proc", "/proc", "--chdir", str(root),
            "codex", "--no-daemon", "--no-alt-screen",
        ]
        master, slave = pty.openpty()
        environment = {key: value for key, value in os.environ.items() if key != "FOIE_GRAS_LIST"}
        environment["TERM"] = "xterm-256color"
        if scenario == "selected":
            environment["FOIE_GRAS_LIST"] = "beta"
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
            process = subprocess.Popen(
                cmd, stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                env=environment,
            )
        finally:
            os.close(slave)
        screen = b""
        prompts = [task]
        commands = {"feed": "feed", "explicit_default": "feed:default", "named": "feed:beta", "large": "feed"}
        selectors = [commands.get(scenario)]
        if scenario == "inline":
            selectors[0] = "feed:beta MUST_STAY_LOCAL_" + secrets.token_hex(12)
        expected = [
            ("beta", named_body) if scenario in ("named", "selected")
            else ("default", body) if scenario in commands else None
        ]
        expected_counts = [int(expected[0] is not None)]
        if scenario in ("named", "selected"):
            prompts.append("FOLLOWUP_" + secrets.token_hex(12))
            selectors.append(None)
            expected.append(("beta", named_body))
            expected_counts.append(1)
        if scenario == "selected":
            prompts.append("DEFAULT_" + secrets.token_hex(12))
            selectors.append("feed")
            expected.append(("default", body))
            expected_counts.append(2)
        if scenario == "refresh":
            prompts.extend([
                "FED_" + secrets.token_hex(12),
                "FOLLOWUP_" + secrets.token_hex(12),
                "REFRESH_" + secrets.token_hex(12),
                "SWITCH_" + secrets.token_hex(12),
                "AFTER_SWITCH_" + secrets.token_hex(12),
            ])
            selectors.extend(["feed", None, "feed:default", "feed:beta", None])
            expected.extend([
                ("default", body), ("default", body), ("default", body.replace(marker, "UPDATED_" + marker)),
                ("beta", named_body), ("beta", named_body),
            ])
            expected_counts.extend([1, 1, 2, 3, 3])
        stage, sent = 0, 0
        command_output_start = 0
        reviewed, early_request = False, False
        quiet = time.monotonic()
        deadline = time.monotonic() + timeout

        def submit(text):
            os.write(master, b"\x1b[200~" + text.encode() + b"\x1b[201~")
            time.sleep(0.1)
            os.write(master, b"\r")

        def next_prompt():
            nonlocal stage, sent, command_output_start
            if scenario == "refresh" and sent == 2:
                write(root / "alpha.py", body.replace(marker, "UPDATED_" + marker))
            if selectors[sent]:
                command_output_start = len(screen)
                submit(selectors[sent])
                stage = 5
            else:
                submit(prompts[sent])
                stage, sent = 4, sent + 1

        while time.monotonic() < deadline and process.poll() is None:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                screen += data
                quiet = time.monotonic()
                if b"\x1b[6n" in data:
                    os.write(master, b"\x1b[1;1R")
            if len(provider.requests) > sent:
                early_request = True
                break
            if stage == 0 and time.monotonic() - quiet > 0.8:
                if b"Hooks need review" in screen:
                    os.write(master, b"\r")  # Startup dialog: Review hooks.
                else:
                    submit("/hooks")
                stage = 1
            elif stage == 1 and b"UserPromptSubmit" in screen and time.monotonic() - quiet > 0.8:
                # This isolated session contains only the generated test hook.
                os.write(master, b"t")
                stage = 2
            elif stage == 2 and "trusted_hash" in (state / "config.toml").read_text():
                reviewed = True
                os.write(master, b"\x1b")
                stage = 3
                quiet = time.monotonic()
            elif stage == 3 and time.monotonic() - quiet > 0.5:
                next_prompt()
            elif stage == 5 and time.monotonic() - quiet > 0.5:
                notice = (b"Submit feed or feed:NAME alone" if scenario == "inline"
                          else b"Enter your task normally.")
                if notice in screen[command_output_start:]:
                    submit(prompts[sent])
                    stage, sent = 4, sent + 1
            elif stage == 4 and f"MOCK_OK_{sent}".encode() in screen:
                if sent == len(prompts):
                    break
                if time.monotonic() - quiet > 0.5:
                    next_prompt()
        request = provider.requests[-1] if provider.requests else {}
        inputs = json.dumps(request.get("input", []))
        contexts = [[
            block.get("text", "")
            for item in request.get("input", [])
            for block in item.get("content", [])
            if isinstance(block, dict) and "foie_gras: current files from list" in block.get("text", "")
        ] for request in provider.requests]
        counts = [len(blocks) for blocks in contexts]
        contents_match = len(contexts) == len(expected) and all(
            not blocks if latest is None else (
                blocks and latest[1] in blocks[-1]
                and f'foie_gras: current files from list "{latest[0]}".' in blocks[-1]
            )
            for blocks, latest in zip(contexts, expected)
        )
        all_requests = json.dumps(provider.requests + provider.title_requests)
        selectors_hidden = all(text not in all_requests for text in (
            "feed:", "FOIE_GRAS_LIST", "MUST_STAY_LOCAL_",
        )) and all(
            block.get("text", "").strip() != "feed"
            for request in provider.requests + provider.title_requests
            for item in request.get("input", [])
            for block in item.get("content", [])
            if isinstance(block, dict)
        )
        local_notice_hidden = "Enter your task normally." not in all_requests
        row = {
            "scenario": scenario, "requests": len(provider.requests),
            "title_requests": len(provider.title_requests),
            "reviewed_in_ui": reviewed, "early_request": early_request,
            "context_counts": counts, "expected_context_counts": expected_counts,
            "contents_match": contents_match, "prompt_copies": inputs.count(task),
            "selectors_hidden": selectors_hidden, "local_notice_hidden": local_notice_hidden,
            "ok": (
                len(provider.requests) == len(prompts) and reviewed and not early_request and not provider.errors
                and counts == expected_counts and contents_match and inputs.count(task) == 1
                and selectors_hidden and local_notice_hidden
                and all(inputs.count(prompt) == 1 for prompt in prompts)
                and f"MOCK_OK_{len(prompts)}".encode() in screen
            ),
        }
        if keep:
            write(root / "request.json", json.dumps(request, indent=2))
            write(root / "requests.json", json.dumps(provider.requests, indent=2))
            write(root / "screen.txt", screen.decode(errors="replace"))
            row["directory"] = str(root)
        if not row["ok"]:
            row["screen"] = screen.decode(errors="replace")[-1500:]
        return row
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        if master is not None:
            os.close(master)
        provider.shutdown()
        provider.server_close()
        worker.join()
        if not keep:
            shutil.rmtree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=35)
    parser.add_argument("--keep", action="store_true")
    available = ["default", "feed", "explicit_default", "named", "selected", "large", "refresh", "inline"]
    parser.add_argument("scenarios", nargs="*", help=", ".join(available) + " (default: all)")
    args = parser.parse_args()
    if not shutil.which("codex") or not shutil.which("bwrap"):
        parser.error("This Linux test requires Codex CLI and bubblewrap (bwrap)")
    scenarios = args.scenarios or available
    if set(scenarios) - set(available):
        parser.error("Unknown scenario")
    failed = False
    for scenario in scenarios:
        row = run(args.timeout, args.keep, scenario)
        print(json.dumps(row), flush=True)
        failed |= not row["ok"]
    raise SystemExit(int(failed))


if __name__ == "__main__":
    main()
