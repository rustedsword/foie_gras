# foie_gras

When a session starts with "implement X" or "fix Y", a coding agent first spends a string of tool calls finding and reading files, even when you already know which ones it needs.

foie_gras lets you list those files once and attach their contents to your prompt. They land in context in the same turn, so the agent can start editing.

Supports Claude Code and Codex CLI.

## Install

[`foie-gras`](foie-gras) is a single script with everything inside. Put it on your PATH and point it at a git repository:

```sh
make install PREFIX=$HOME/.local    # or copy foie-gras anywhere on your PATH
foie-gras path/to/repo
```

It writes a Claude Code mod to `.claude/skills/foie-gras/` and the Codex hook to `.codex/`, and creates an empty `.foie_gras/default`. Rerun the updated script to upgrade the adapters, preserving your file lists. Claude Code loads the mod once you trust the repository. Codex needs Python 3.10+; approve the hook when Codex asks, or in `/hooks`.

`make` rebuilds `foie-gras` from `foie-gras.in` and the adapter sources; commit it with them.

## File lists

Put the files in `.foie_gras/default`, one path, glob (`**` works) or directory per line:

```
# .foie_gras/default
src/auth/**/*.py
docs/auth.md
tests/test_login.py
```

For more lists, add files next to `default`, e.g. `.foie_gras/auth`. A plain `.foie_gras` file also works as the default list. Every entry must match a file: otherwise the requested load fails, and the error names the entry.

## Codex CLI

Submit a feed command by itself, then enter your task:

| Command | File list |
|-|-|
| `feed` or `feed:default` | `.foie_gras/default` |
| `feed:auth` | `.foie_gras/auth` |

Each command reads fresh file contents into the session. Repeat it to refresh a list, or use `feed:NAME` to load another.

For an initial preload, choose a list before starting Codex:

```sh
FOIE_GRAS_LIST=default codex exec "Fix the login bug"   # default list
FOIE_GRAS_LIST=auth codex exec "Fix the login bug"      # auth list
```

`FOIE_GRAS_LIST` also works with interactive `codex`, tasks read from stdin (`codex exec -`), and `--ephemeral`. Feed commands take precedence over the environment selection.

Implementation details, source references, and tests: [docs/codex.md](docs/codex.md).

## Claude Code

| You type | Files read with that prompt |
|-|-|
| `feed: <prompt>` | `.foie_gras/default` |
| `feed:auth <prompt>` | `.foie_gras/auth` |

Claude gets `<prompt>` as you typed it, and its turn starts with Read calls for the listed files: Claude Code reads them with its Read tool, as if Claude had asked, and they count as read. `claude -p "feed: <prompt>"` works the same. To use it in every project, copy `claude/foie-gras` into `~/.claude/skills/`.

To see it work, run `claude` in [`example/`](example/).

How it works, how it compares to CLAUDE.md imports and hooks, limits and tests: [docs/claude-code.md](docs/claude-code.md).
