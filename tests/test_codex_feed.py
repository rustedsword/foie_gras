#!/usr/bin/env python3
"""Manifest and hook checks; no Codex installation or inference required."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "codex/feed.py"
spec = importlib.util.spec_from_file_location("feed", SCRIPT)
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)


class FeedTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(feed.os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        feed.os.environ.pop("FOIE_GRAS_LIST", None)
        self.temporary = tempfile.TemporaryDirectory(prefix="fg-feed-unit-")
        self.root = Path(self.temporary.name)
        self.write(".foie_gras/default", "src/**/*.py\n")
        self.write("src/alpha.py", 'ALPHA = "first"\n')

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def text(self, name="default"):
        return feed.file_context(self.root, name)

    def event(self, prompt="change alpha", cwd=None):
        return {"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                "cwd": str(cwd or self.root), "transcript_path": str(self.root / "session.jsonl")}

    def record_context(self, result):
        entry = {"type": "response_item", "payload": {
            "type": "message", "role": "developer", "content": [{
                "type": "input_text", "text": result["hookSpecificOutput"]["additionalContext"],
            }],
        }}
        with (self.root / "session.jsonl").open("a", encoding="utf-8") as transcript:
            transcript.write(json.dumps(entry) + "\n")

    def test_files_globs_directories_spaces_hidden_files_and_deduplication(self):
        self.write("src/.hidden.py", "HIDDEN\n")
        self.write("src/nested/file with spaces.py", "SPACES\n")
        self.write("src/nested/notes.txt", "NOTES\n")
        (self.root / "alias.py").symlink_to(self.root / "src/alpha.py")
        (self.root / "src/loop").symlink_to(self.root / "src", target_is_directory=True)
        self.write(".foie_gras/default", "# files\n\nsrc/**/*.py\nsrc\n./src/alpha.py\nalias.py")
        text = self.text()
        for body in ('ALPHA = "first"', "HIDDEN", "SPACES", "NOTES"):
            self.assertEqual(text.count(body), 1)
        self.assertIn("file with spaces.py", text)

    def test_named_list_and_fresh_contents(self):
        self.write(".foie_gras/beta", "src/beta.py\n")
        self.write("src/beta.py", "BETA_FIRST\n")
        self.assertIn("BETA_FIRST", self.text("beta"))
        self.write("src/beta.py", "BETA_SECOND\n")
        text = self.text("beta")
        self.assertIn("BETA_SECOND", text)
        self.assertNotIn("BETA_FIRST", text)
        self.assertNotIn("ALPHA", text)

    def test_plain_manifest_and_nested_working_directory(self):
        (self.root / ".foie_gras/default").unlink()
        (self.root / ".foie_gras").rmdir()
        self.write(".foie_gras", "src/alpha.py")
        self.assertEqual(feed.manifest_root(self.root / "src"), self.root)
        self.assertIn('ALPHA = "first"', self.text())
        with self.assertRaises(feed.FeedError):
            self.text("beta")

    def test_missing_empty_binary_and_invalid_lists_block(self):
        for contents in ("missing.py\n", "# empty\n", "src/alpha.py\nmissing.py\n"):
            self.write(".foie_gras/default", contents)
            with self.assertRaises(feed.FeedError):
                self.text()
            self.assertEqual(feed.hook(self.event())["decision"], "block")
        self.write(".foie_gras/default", "src/alpha.py\n")
        for data in (b"\0binary", b"\xffbad"):
            (self.root / "src/alpha.py").write_bytes(data)
            with self.assertRaises((feed.FeedError, UnicodeError)):
                self.text()
            self.assertEqual(feed.hook(self.event())["decision"], "block")
        for name in ("../alpha", ".", "..", ""):
            with self.assertRaises(feed.FeedError):
                self.text(name)

    def test_source_fences_crlf_and_missing_final_newline_are_preserved(self):
        body = b"alpha\r\n```\r\n````\r\nomega"
        (self.root / "src/alpha.py").write_bytes(body)
        text = self.text()
        self.assertIn(body.decode(), text)
        self.assertIn("`````\n", text)
        self.assertIn("final newline: no", text)

    def test_manifest_search_stops_at_another_repository(self):
        nested = self.root / "nested"
        (nested / ".git").mkdir(parents=True)
        self.assertIsNone(feed.manifest_root(nested))
        self.assertEqual(feed.hook(self.event(cwd=nested)), {})
        self.assertEqual(feed.hook(self.event("feed:auth", nested))["decision"], "block")

    def test_default_and_named_prompts_keep_task_out_of_context(self):
        self.write(".foie_gras/default", "src/alpha.py\n")
        self.write(".foie_gras/beta", "src/beta.py\n")
        self.write("src/beta.py", "BETA\n")
        for prompt, included, excluded in (("change alpha", "ALPHA", "BETA"),
                                            ("feed:beta", "BETA", "ALPHA")):
            result = feed.hook(self.event(prompt))
            context = result["hookSpecificOutput"]["additionalContext"]
            self.assertIn(included, context)
            self.assertNotIn(excluded, context)
            self.assertNotIn(prompt, context)
            self.assertNotIn("feed:", context)
            self.assertEqual(result.get("continue", True), not prompt.startswith("feed:"))

    def test_ordinary_followups_skip_files_even_after_compaction_or_resume(self):
        self.record_context(feed.hook(self.event()))
        # If the hook tried to read the list again, this would block the prompt.
        (self.root / "src/alpha.py").unlink()
        with (self.root / "session.jsonl").open("a") as transcript:
            transcript.write(json.dumps({"type": "compacted", "payload": {}}) + "\n")
            transcript.write('{"unfinished":')
        self.assertEqual(feed.hook(self.event("continue")), {})
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.root,
                                input=json.dumps(self.event("continue")), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        # A new session gets its own initial preload.
        self.write("src/alpha.py", "NEW_SESSION\n")
        event = {**self.event(), "transcript_path": str(self.root / "new-session.jsonl")}
        self.assertIn("NEW_SESSION", feed.hook(event)["hookSpecificOutput"]["additionalContext"])

    def test_explicit_lists_reload_and_count_as_the_initial_preload(self):
        self.write(".foie_gras/default", "src/alpha.py\n")
        self.write(".foie_gras/beta", "src/beta.py\n")
        self.write("src/beta.py", "BETA_FIRST\n")
        self.record_context(feed.hook(self.event("feed:beta")))
        self.assertEqual(feed.hook(self.event("continue")), {})
        self.write("src/beta.py", "BETA_SECOND\n")
        result = feed.hook(self.event("feed:beta"))
        self.assertIn("BETA_SECOND", result["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("BETA_FIRST", result["hookSpecificOutput"]["additionalContext"])
        self.record_context(result)
        self.write("src/alpha.py", "ALPHA_UPDATED\n")
        result = feed.hook(self.event("feed:default"))
        self.assertIn("ALPHA_UPDATED", result["hookSpecificOutput"]["additionalContext"])
        self.record_context(result)
        self.assertEqual(feed.hook(self.event("continue")), {})
        self.assertEqual(feed.hook(self.event("feed:missing"))["decision"], "block")

    def test_environment_selects_initial_files_and_explicit_command_overrides_it(self):
        self.write(".foie_gras/default", "src/alpha.py\n")
        self.write(".foie_gras/beta", "src/beta.py\n")
        self.write("src/beta.py", "BETA\n")
        feed.os.environ["FOIE_GRAS_LIST"] = "beta"
        event = self.event("explain this code")
        result = feed.hook(event)
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("BETA", context)
        self.assertNotIn("ALPHA", context)
        self.assertNotIn("FOIE_GRAS_LIST", context)
        self.assertNotIn("feed:", context)
        self.assertNotIn("continue", result)
        self.assertEqual(event["prompt"], "explain this code")
        self.record_context(result)
        self.assertEqual(feed.hook(self.event("continue")), {})
        result = feed.hook(self.event("feed:default"))
        self.assertFalse(result["continue"])
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ALPHA", context)
        self.assertNotIn("BETA", context)

    def test_invalid_environment_selection_blocks_instead_of_loading_default(self):
        for name in ("", "missing", "../default"):
            feed.os.environ["FOIE_GRAS_LIST"] = name
            self.assertEqual(feed.hook(self.event())["decision"], "block")
        nested = self.root / "nested"
        (nested / ".git").mkdir(parents=True)
        feed.os.environ["FOIE_GRAS_LIST"] = "default"
        self.assertEqual(feed.hook(self.event(cwd=nested))["decision"], "block")

    def test_inline_selectors_block_instead_of_leaking_into_the_prompt(self):
        for prompt in ("feed:default edit alpha", "  feed:default\nedit alpha"):
            event = self.event(prompt)
            result = feed.hook(event)
            self.assertEqual(result["decision"], "block")
            self.assertIn("alone", result["reason"])
            self.assertNotIn("hookSpecificOutput", result)
            self.assertEqual(event["prompt"], prompt)
        result = feed.hook(self.event(" \nfeed:default\n "))
        self.assertFalse(result["continue"])
        self.assertIn("ALPHA", result["hookSpecificOutput"]["additionalContext"])

    def test_only_recorded_hook_context_counts_as_a_preload(self):
        # Environment messages, quoted hook output, and unrelated hook output
        # must not prevent the initial preload.
        entries = [{"type": "response_item", "payload": {"role": role, "content": [
            {"type": "input_text", "text": text},
        ]}} for role, text in (
            ("user", "<environment_context>test</environment_context>"),
            ("user", feed.CONTEXT_PREFIX + '"default".'),
            ("developer", "Instructions about " + feed.CONTEXT_PREFIX),
        )]
        self.write("session.jsonl", "\n".join(map(json.dumps, entries)) + '\n{"unfinished":')
        self.assertIn("ALPHA", feed.hook(self.event())["hookSpecificOutput"]["additionalContext"])

    def test_ephemeral_exec_without_a_transcript_loads_its_prompt(self):
        event = {**self.event(), "transcript_path": None}
        self.assertIn("ALPHA", feed.hook(event)["hookSpecificOutput"]["additionalContext"])

    def test_hook_input_never_executes_prompt_text(self):
        task = "Fix Bob's `code`; $(touch unexpected)\nThen explain."
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.root,
                                input=json.dumps(self.event(task)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ALPHA", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertFalse((self.root / "unexpected").exists())

    def test_install_preserves_other_hooks_and_is_idempotent(self):
        original = {"description": "user hooks", "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo custom"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
        }}
        path = self.write(".codex/hooks.json", json.dumps(original))
        with contextlib.redirect_stdout(io.StringIO()):
            feed.install(self.root)
            feed.install(self.root)
        actual = json.loads(path.read_text())
        self.assertEqual(actual["description"], original["description"])
        self.assertEqual(actual["hooks"]["Stop"], original["hooks"]["Stop"])
        handlers = [h for group in actual["hooks"]["UserPromptSubmit"] for h in group["hooks"]]
        self.assertEqual(len(handlers), 2)
        self.assertEqual(handlers[0]["command"], "echo custom")
        self.assertEqual(handlers[1]["additionalContextLimit"], 0)
        self.assertNotIn("async", handlers[1])
        path.write_text('{"hooks": []}')
        with self.assertRaises((TypeError, AttributeError)):
            feed.install(self.root)
        self.assertEqual(path.read_text(), '{"hooks": []}')


if __name__ == "__main__":
    unittest.main()
