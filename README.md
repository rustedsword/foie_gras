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

It writes the Claude Code skill to `.claude/skills/feed/` and the Codex hook to `.codex/`, and creates an empty `.foie_gras/default`. Rerun it to update. Codex needs Python 3.10+; approve the hook when Codex asks, or in `/hooks`.

`make` rebuilds `foie-gras` from `foie-gras.in` and the adapter sources; commit it with them.

## File lists

Put the files in `.foie_gras/default`, one path, glob (`**` works) or directory per line:

```
# .foie_gras/default
src/auth/**/*.py
docs/auth.md
tests/test_login.py
```

For more lists, add files next to `default`, e.g. `.foie_gras/auth`. A plain `.foie_gras` file also works as the default list. An empty list loads nothing. Every entry must match a file: otherwise the prompt doesn't run, and the error names the entry.

## Codex CLI

Type your prompts normally:

| You type inside Codex | Files loaded with that prompt |
|-|-|
| `Fix the login bug` (first prompt) | `.foie_gras/default` |
| Ordinary follow-up | Nothing added |
| `feed:auth` (submit alone) | `.foie_gras/auth`; then enter your task |
| `feed:default` (submit alone) | `.foie_gras/default` again; then enter your task |

Files load once at the start of a session. Submit `feed:NAME` alone whenever you want to load another list or refresh one already loaded. The hook consumes that command locally without a model call, then your next ordinary prompt uses the loaded files. The model receives the files and your task, with no selector command or instructions about selectors. Ordinary follow-ups do not reload files. No skill or special launcher is needed.

For non-interactive work, choose the initial list before starting Codex:

```sh
codex exec "Fix the login bug"                         # default list
FOIE_GRAS_LIST=auth codex exec "Fix the login bug"      # auth list
```

`FOIE_GRAS_LIST` also works with interactive `codex`. It selects the initial preload without changing your prompt.

Verified with a real edit while file-reading tools were blocked: Codex used only `apply_patch`. Setup, source references, and reproducible tests: [docs/codex.md](docs/codex.md).

## Claude Code

| You type | Result |
|-|-|
| `/feed <prompt>` | the list is attached to your prompt, in one turn |
| `/feed` | only attaches; Claude answers `Ready.` |
| `claude "/feed <prompt>"` | the same, straight from the shell |

For named lists, run `.claude/skills/feed/feed.sh --sync` to get `/feed-auth`. Rerun it after adding or removing a list; editing one needs nothing. To get `/feed` in every project, copy `claude/skills/feed` into `~/.claude/skills/` instead.

To see it work, run `claude` in [`example/`](example/).

How it works, how it compares to CLAUDE.md imports and hooks, limits and tests: [docs/claude-code.md](docs/claude-code.md).
