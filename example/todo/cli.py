import argparse

from .store import Store


def main(argv=None, store=None):
    parser = argparse.ArgumentParser(prog="todo")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("add").add_argument("title")
    commands.add_parser("list")
    commands.add_parser("done").add_argument("id", type=int)
    args = parser.parse_args(argv)
    store = store or Store()

    if args.command == "add":
        print(f"added #{store.add(args.title).id}")
    elif args.command == "list":
        for task in store.load():
            print(f"[{'x' if task.done else ' '}] #{task.id} {task.title}")
    elif args.command == "done":
        store.complete(args.id)
        print(f"done #{args.id}")
