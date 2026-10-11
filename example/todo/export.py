import csv
import sys

from .store import Store


def main():
    writer = csv.writer(sys.stdout)
    writer.writerow(["id", "title", "done", "created"])
    for task in Store().load():
        writer.writerow([task.id, task.title, task.done, task.created])


if __name__ == "__main__":
    main()
