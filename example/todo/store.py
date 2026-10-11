import json
import os
from dataclasses import asdict
from pathlib import Path

from .models import Task


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("TODO_FILE", "todo.json"))

    def load(self):
        if not self.path.exists():
            return []
        return [Task(**t) for t in json.loads(self.path.read_text())]

    def save(self, tasks):
        self.path.write_text(json.dumps([asdict(t) for t in tasks], indent=2) + "\n")

    def add(self, title):
        tasks = self.load()
        task = Task(id=max((t.id for t in tasks), default=0) + 1, title=title)
        self.save(tasks + [task])
        return task

    def complete(self, task_id):
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                task.done = True
                self.save(tasks)
                return task
        raise KeyError(task_id)
