import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from todo.cli import main
from todo.store import Store


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "todo.json")

    def tearDown(self):
        self.dir.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            main(list(argv), self.store)
        return out.getvalue()

    def test_add_and_list(self):
        self.assertEqual(self.run_cli("add", "buy milk"), "added #1\n")
        self.assertEqual(self.run_cli("list"), "[ ] #1 buy milk\n")

    def test_done(self):
        self.run_cli("add", "buy milk")
        self.run_cli("done", "1")
        self.assertEqual(self.run_cli("list"), "[x] #1 buy milk\n")
