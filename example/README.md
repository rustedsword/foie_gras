# Example

A tiny todo CLI with foie_gras set up and two lists:

- `.foie_gras/default`: model, storage, CLI and tests
- `.foie_gras/export`: the CSV exporter, model and storage

## Codex CLI

```sh
cd example
codex
```

Review and trust the foie_gras hook when Codex asks, or open `/hooks`. Then type:

```text
feed
```

The hook loads the five default files. Then submit your task:

```text
Add a --priority option (low, normal, high; default normal) to `todo add`, show it in `todo list` and cover it in tests.
```

For the exporter, submit:

```text
feed:export
```

Then submit your task:

```text
Add a --format json option to the exporter
```

`.codex/hooks.json` resolves `codex/feed.py` from the repository root, so the
example works wherever this repository is cloned.

For non-interactive use from `example/`:

```sh
FOIE_GRAS_LIST=default codex exec "Explain how the todo CLI works"
FOIE_GRAS_LIST=export codex exec "Explain how the exporter works"
```

## Claude Code

```sh
cd example
claude
```

Then type:

```
feed: Add a --priority option (low, normal, high; default normal) to `todo add`, show it in `todo list` and cover it in tests.
```

Claude's turn starts by reading the five default files. `feed:export Add a --format json option to the exporter` does the same with the export list.

## opencode

```sh
cd example
opencode
```

Then type:

```
feed: Add a --priority option (low, normal, high; default normal) to `todo add`, show it in `todo list` and cover it in tests.
```

The model gets the prompt with the five default files, as read calls of its own. `feed:export Add a --format json option to the exporter` does the same with the export list.

## The app itself

```sh
python3 -m todo add "buy milk"
python3 -m todo list
python3 -m unittest
```

`.claude/skills/foie-gras` is a symlink into `../claude/`, and `.opencode` one to `../opencode`.
