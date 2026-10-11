import tempfile
import unittest
from pathlib import Path

from todo.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "todo.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_add_assigns_increasing_ids(self):
        self.assertEqual(self.store.add("a").id, 1)
        self.assertEqual(self.store.add("b").id, 2)

    def test_complete(self):
        self.store.add("a")
        self.store.complete(1)
        self.assertTrue(self.store.load()[0].done)

    def test_complete_unknown_id(self):
        with self.assertRaises(KeyError):
            self.store.complete(42)
