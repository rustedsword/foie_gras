#!/usr/bin/env python3
"""Checks a copy of the built foie-gras in a throwaway git repository; no agents required."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
COMMAND = 'python3 "$(git rev-parse --show-toplevel)/.codex/foie_gras.py"'


class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["make", "-s", "-C", str(REPO), "foie-gras"], check=True, capture_output=True)
        cls.bin = tempfile.TemporaryDirectory(prefix="fg-bin-")
        cls.installer = Path(cls.bin.name) / "foie-gras"
        shutil.copy(REPO / "foie-gras", cls.installer)

    @classmethod
    def tearDownClass(cls):
        cls.bin.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fg-install-")
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "src").mkdir()
        (self.root / "src/alpha.py").write_text('ALPHA = "first"\n')
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in ("FOIE_GRAS_LIST", "CLAUDE_PROJECT_DIR")}

    def tearDown(self):
        self.temporary.cleanup()

    def install(self):
        return subprocess.run([str(self.installer), f"{self.root}/src/"], cwd=self.bin.name,
                              env=self.environment, capture_output=True, text=True, check=True)

    def handlers(self):
        config = json.loads((self.root / ".codex/hooks.json").read_text())
        return [handler["command"] for group in config["hooks"]["UserPromptSubmit"]
                for handler in group["hooks"]]

    def codex_hook(self):
        event = {"hook_event_name": "UserPromptSubmit", "prompt": "fix it",
                 "cwd": str(self.root / "src"), "transcript_path": None}
        result = subprocess.run(["sh", "-c", COMMAND], cwd=self.root / "src", env=self.environment,
                                input=json.dumps(event), capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def claude_feed(self, check=True):
        result = subprocess.run([str(self.root / ".claude/skills/feed/feed.sh")], cwd=self.root / "src",
                                env={**self.environment, "CLAUDE_PROJECT_DIR": str(self.root)},
                                capture_output=True, text=True, check=check)
        return result.stdout if check else result

    def test_missing_entry_stops_both_agents(self):
        self.install()
        (self.root / ".foie_gras/default").write_text("src/alpha.py\nsrc/missing.py\n")
        result = self.claude_feed(check=False)
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("'src/missing.py'", result.stderr)
        self.assertIn("'src/missing.py'", self.codex_hook()["reason"])

    def test_installs_both_agents_with_an_empty_default_list(self):
        self.assertIn(str(self.root), self.install().stdout)
        self.assertEqual((self.root / ".foie_gras/default").read_text(), "")
        self.assertEqual(self.handlers(), [COMMAND])
        self.assertEqual(self.codex_hook(), {})
        self.assertEqual(self.claude_feed(), "")
        (self.root / ".foie_gras/default").write_text("src/*.py\n")
        self.assertIn('ALPHA = "first"', self.codex_hook()["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.claude_feed(), "@src/alpha.py\n")

    def test_rerun_keeps_lists_and_other_hooks_and_replaces_its_own(self):
        (self.root / ".codex").mkdir()
        (self.root / ".codex/hooks.json").write_text(json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "echo custom"}]},
            {"hooks": [{"type": "command", "command": "python3 /old/codex/feed.py",
                        "statusMessage": "Reading foie_gras files"}]},
        ]}}))
        (self.root / ".foie_gras").mkdir()
        (self.root / ".foie_gras/default").write_text("src/alpha.py\n")
        (self.root / ".foie_gras/auth").write_text("src/alpha.py\n")
        self.install()
        self.assertIn("/feed-auth", self.install().stdout)
        self.assertEqual((self.root / ".foie_gras/default").read_text(), "src/alpha.py\n")
        self.assertEqual(self.handlers(), ["echo custom", COMMAND])
        self.assertTrue((self.root / ".claude/skills/feed-auth/SKILL.md").is_file())

    def test_plain_list_file_is_kept(self):
        (self.root / ".foie_gras").write_text("src/alpha.py\n")
        self.install()
        self.assertEqual((self.root / ".foie_gras").read_text(), "src/alpha.py\n")
        self.assertEqual(self.claude_feed(), "@src/alpha.py\n")

    def test_refuses_a_directory_outside_git(self):
        with tempfile.TemporaryDirectory(prefix="fg-install-") as directory:
            result = subprocess.run([str(self.installer), directory], env=self.environment, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
