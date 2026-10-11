# foie_gras

Force-feed a coding agent a known set of files at session start, so it doesn't spend tool calls finding and re-reading them and can edit them right away.

## Is there a universal way?

No. All three agents can start with an initial prompt, but what `@path` does in it differs:

- **Claude Code**: `@path` attaches the file as if Read ran. Covered below.
- **OpenCode**: `@path` in the TUI and in commands, `opencode run -f`, `instructions` in `opencode.json`. TODO.
- **Codex**: `AGENTS.md` and the initial prompt; `codex exec -i` attaches images only. TODO.

So foie_gras is one manifest plus a small adapter and test suite per agent.

## Manifest

`.foie_gras` in the project root. One path, glob (`**` works) or directory per line; lines starting with `#` are comments.

```
src/auth/**/*.py
docs/auth.md
tests/test_login.py
```

`FOIE_GRAS=path/to/list claude` picks another manifest.

## Claude Code

The agent part needs v2.1.281+. Tested on 2.1.296.

### Install

```sh
mkdir -p .claude/skills .claude/agents
cp -r claude/skills/feed .claude/skills/
cp claude/agents/foie-gras.md .claude/agents/
```

Use `~/.claude/` instead of `.claude/` to install for all projects.

To feed automatically at session start, add to `.claude/settings.local.json`:

```json
{
  "agent": "foie-gras",
  "permissions": { "deny": ["Agent(foie-gras)"] }
}
```

### Use

| Command | Result |
|-|-|
| `claude` | `/feed` runs, Claude answers `Ready.` |
| `claude "fix the login bug"` | runs as `/feed fix the login bug` |
| `/feed [task]` | feed or re-feed at any point |
| `claude --agent foie-gras` | per-launch alternative to the `agent` setting |

### How it works

- `feed.sh` turns the manifest into `@path` lines. The skill injects them with `` !`feed.sh` `` and Claude Code expands each one like a typed `@path`: the file is attached in Read result format and counts as read.
- The agent has an empty body, so the default system prompt stays. Its `initialPrompt: /feed` is prepended to the first prompt of every session.
- The deny rule keeps Claude from spawning `foie-gras` as a subagent.

### Why not CLAUDE.md imports or hooks

`tests/claude.py`, Claude Code 2.1.296. Every mechanism below puts the content in context.

| Mechanism | Counts as read¹ | Re-reads²: Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|-|-|-|-|-|
| nothing | – | 2 | 2 | 2 |
| `@path` lines in CLAUDE.md | no | 1.2 | 0 | 2 |
| same + "do not Read them again" | no | 1.2 | 0 | 0 |
| SessionStart `additionalContext` | no | 2 | 2 | 2 |
| `--append-system-prompt` | no | 1.2 | 2 | 1 |
| `--resume --fork-session` of a fed session | no | 1.8 | 0 | 0 |
| `@path` in the prompt | yes | 2 | 0 | 0 |
| SessionStart `initialUserMessage` (`-p` only) | yes | 2 | 0 | 0 |
| command or skill with plain `@path` lines | yes | 0.5–0.8 | 0 | 0 |
| **`/feed` skill** | yes | 0 | 0 | 0 |
| **`foie-gras` agent** | yes | 0 | 0 | 0 |

¹ Edit succeeds with the Read tool unavailable (`--strict`), which makes every model enforce read-before-edit.
² Read/Grep/Glob/Bash calls for "edit one fed file, quote another". Mean of 4 runs for Haiku, 1–3 for Sonnet/Opus.

5.5 models may Edit a file they haven't read when Read is available and wouldn't prompt, so "counts as read" only matters for permission-gated paths and partial reads. In practice the question is whether the model trusts what it was given: attachments look like Read results, and the skill's "count as read" line gets Haiku there too.

CLAUDE.md imports with that line are a zero-setup option for Sonnet/Opus. But they load in every session and every subagent, and don't count as read.

### Limits

- A file over 25k tokens is silently skipped, not truncated. Raise `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`, e.g. `"env": {"CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS": "100000"}` in settings. Files over 256 KB are never attached.
- The skill needs the Bash tool, and its `!` command must be pre-approved; `allowed-tools` does that for `feed.sh`. Denying `Bash` or setting `disableSkillShellExecution` breaks it; fall back to plain `@path` lines in `SKILL.md`.
- `initialPrompt` also runs on `--resume` and re-attaches the files. Read state isn't restored on resume, so that's useful, at the cost of a second copy in context.
- With `agent` in settings, `claude -p` in that project gets `/feed` too. If you script `claude -p` there, alias `claude --agent foie-gras` instead.
- Fed files cost context in every session; keep manifests task-sized.

## Tests

```sh
python3 tests/claude.py                          # re-reads, Sonnet, all mechanisms
python3 tests/claude.py --model opus --repeat 3
python3 tests/claude.py --strict --model haiku   # counts-as-read verdicts, exit 1 on mismatch
python3 tests/claude.py --strict --model haiku adapter_large adapter_large_raised
python3 tests/claude_tui.py                      # real interactive session through a pty
```

Each run uses a throwaway git repo and purges its Claude Code state afterwards. User settings and MCP servers are skipped; `claude_tui.py` accepts the trust dialog for its own temp dir. Per mechanism a run costs about $0.002 on Haiku, $0.03 on Sonnet and $0.06 on Opus.
