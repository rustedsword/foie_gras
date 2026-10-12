#!/usr/bin/env python3
"""Print the models opencode offers free of charge and without an account, one provider/model per line."""

import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time


def isolated(base):
    """An environment with no config, account, sessions or background service of yours."""
    home = base / "home"
    (base / "tmp").mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(base / "tmp"),
        "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local/state"),
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
    }


def catalog(environment, cwd, timeout=60):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = {**environment, "OPENCODE_SERVER_PASSWORD": secrets.token_urlsafe(16)}
    server = subprocess.Popen(["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(port)], cwd=cwd,
                              env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # The server answers before it has loaded every provider; wait until two lists in a row agree.
        previous, deadline = None, time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(1)
            result = subprocess.run(["opencode", "api", "--server", f"http://127.0.0.1:{port}", "model.list"], cwd=cwd,
                                    env=environment, capture_output=True, text=True, timeout=30)
            models = json.loads(result.stdout)["data"] if result.returncode == 0 else []
            if models and models == previous:
                return models
            previous = models
        raise TimeoutError("opencode did not list its models")
    finally:
        server.terminate()
        server.wait()


def free(models):
    return sorted(f"{m['providerID']}/{m['id']}" for m in models
                  if m.get("cost") and all(tier.get("input") == 0 and tier.get("output") == 0 for tier in m["cost"])
                  and m.get("capabilities", {}).get("tools") and m.get("status") == "active")


def main():
    base = Path(tempfile.mkdtemp(prefix="fg-opencode-models-"))
    try:
        print("\n".join(free(catalog(isolated(base), base))))
    finally:
        shutil.rmtree(base)


if __name__ == "__main__":
    main()
