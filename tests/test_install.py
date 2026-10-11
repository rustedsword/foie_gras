#!/usr/bin/env python3
"""Checks a copy of the built foie-gras in a throwaway git repository; no agents required."""

import json
import os
from pathlib import Path
import re
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
        self.root = Path(self.temporary.name).resolve()
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

    def codex_hook(self, prompt="fix it"):
        event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                 "cwd": str(self.root / "src"), "transcript_path": None}
        result = subprocess.run(["sh", "-c", COMMAND], cwd=self.root / "src", env=self.environment,
                                input=json.dumps(event), capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def claude_files(self, name="default"):
        return subprocess.run(["python3", str(self.root / ".claude/skills/foie-gras/feed.py"), f"--files={name}"],
                              cwd=self.root / "src", env=self.environment, capture_output=True, text=True)

    def test_missing_entry_stops_both_agents(self):
        self.install()
        (self.root / ".foie_gras/default").write_text("src/alpha.py\nsrc/missing.py\n")
        result = self.claude_files()
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("'src/missing.py'", result.stderr)
        self.assertEqual(self.codex_hook(), {})
        self.assertIn("'src/missing.py'", self.codex_hook("feed")["reason"])

    def test_installs_both_agents_with_an_empty_default_list(self):
        self.assertIn(str(self.root), self.install().stdout)
        self.assertEqual((self.root / ".foie_gras/default").read_text(), "")
        self.assertEqual(self.handlers(), [COMMAND])
        mod = self.root / ".claude/skills/foie-gras"
        self.assertEqual(json.loads((mod / ".claude-plugin/plugin.json").read_text())["name"], "foie-gras")
        self.assertEqual(json.loads((mod / "hooks/hooks.json").read_text()), {"modules": ["./register.ts"]})
        self.assertIn("turn.step", (mod / "hooks/register.ts").read_text())
        self.assertEqual(self.codex_hook(), {})
        self.assertIn("contains no files", self.claude_files().stderr)
        (self.root / "src/b c.py").write_text("B = 1\n")
        (self.root / ".foie_gras/default").write_text("src/*.py\n")
        self.assertEqual(self.codex_hook(), {})
        result = self.codex_hook("feed")
        self.assertIn('ALPHA = "first"', result["hookSpecificOutput"]["additionalContext"])
        self.assertFalse(result["continue"])
        self.assertEqual(self.codex_hook("feed:default"), result)
        self.assertEqual(self.claude_files().stdout, f"{self.root}/src/alpha.py\n{self.root}/src/b c.py\n")

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
        self.install()
        self.assertEqual((self.root / ".foie_gras/default").read_text(), "src/alpha.py\n")
        self.assertEqual(self.handlers(), ["echo custom", COMMAND])
        self.assertEqual(self.claude_files("auth").stdout, f"{self.root}/src/alpha.py\n")
        self.assertEqual(self.codex_hook(), {})
        self.assertIn('ALPHA = "first"', self.codex_hook("feed")["hookSpecificOutput"]["additionalContext"])

    def test_both_agents_resolve_crlf_lists_absolute_paths_and_aliases_alike(self):
        self.install()
        (self.root / "src/beta.py").write_text("BETA = 2\n")
        (self.root / "alias.py").symlink_to(self.root / "src/alpha.py")
        (self.root / ".foie_gras/default").write_text(f"src/alpha.py\r\nalias.py\r\n{self.root}/src/beta.py\r\n")
        files = [str(self.root / "src/alpha.py"), str(self.root / "src/beta.py")]
        self.assertEqual(self.claude_files().stdout.splitlines(), files)
        context = self.codex_hook("feed")["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(re.findall(r'^File: "(.+)" \(', context, re.M), files)

    def test_plain_list_file_is_kept(self):
        (self.root / ".foie_gras").write_text("src/alpha.py\n")
        self.install()
        self.assertEqual((self.root / ".foie_gras").read_text(), "src/alpha.py\n")
        self.assertEqual(self.claude_files().stdout, f"{self.root}/src/alpha.py\n")
        self.assertEqual(self.codex_hook(), {})
        result = self.codex_hook("feed")
        self.assertIn('ALPHA = "first"', result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(result, self.codex_hook("feed:default"))

    def test_rerun_removes_files_of_earlier_versions(self):
        skills = self.root / ".claude/skills"
        for path, text in (("feed/feed.sh", ""), ("feed-auth/SKILL.md", "!`${CLAUDE_SKILL_DIR}/../feed/feed.sh auth`\n"),
                           ("mine/SKILL.md", "mine\n"), ("foie-gras/files.sh", "")):
            (skills / path).parent.mkdir(parents=True, exist_ok=True)
            (skills / path).write_text(text)
        self.install()
        self.assertEqual(sorted(p.name for p in skills.iterdir()), ["foie-gras", "mine"])
        self.assertFalse((skills / "foie-gras/files.sh").exists())

    def test_refuses_a_directory_outside_git(self):
        with tempfile.TemporaryDirectory(prefix="fg-install-") as directory:
            result = subprocess.run([str(self.installer), directory], env=self.environment, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
