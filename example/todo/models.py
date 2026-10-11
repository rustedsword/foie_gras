from dataclasses import dataclass, field
from datetime import date


@dataclass
class Task:
    id: int
    title: str
    done: bool = False
    created: str = field(default_factory=lambda: date.today().isoformat())
