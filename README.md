# foie_gras

When a session starts with "implement X" or "fix Y", a coding agent first spends a string of tool calls finding and reading files, even when you already know which ones it needs.

foie_gras lets you list those files once and attach them to your prompt. They land in context in the same turn and count as already read, so Claude edits them without a Read first and doesn't re-read them.

Only Claude Code for now. OpenCode and Codex load files differently and need their own adapters.

## Install

Copy the skill into your project, or into `~/.claude/skills/` for all projects:

```sh
mkdir -p .claude/skills
cp -r path/to/foie_gras/claude/skills/feed .claude/skills/
```

Put the files in `.foie_gras/default`, one path, glob (`**` works) or directory per line:

```
# .foie_gras/default
src/auth/**/*.py
docs/auth.md
tests/test_login.py
```

## Use

| You type | Result |
|-|-|
| `/feed <prompt>` | the list is attached to your prompt, in one turn |
| `/feed` | only attaches; Claude answers `Ready.` |
| `claude "/feed <prompt>"` | the same, straight from the shell |

For more lists, add files next to `default`, e.g. `.foie_gras/auth`, and run `.claude/skills/feed/feed.sh --sync` to get `/feed-auth`. Rerun it after adding or removing a list; editing one needs nothing.

To see it work, run `claude` in [`example/`](example/).

How it works, how it compares to CLAUDE.md imports and hooks, limits and tests: [docs/claude-code.md](docs/claude-code.md).
