# foie_gras

Force-feed a coding agent a known set of files along with your first prompt, so it doesn't spend tool calls finding and re-reading them and can edit them right away.

To see it work, run `claude` in [`example/`](example/) and type `/feed`.

## Is there a universal way?

No. All three agents can start with an initial prompt, but what `@path` does in it differs:

- **Claude Code**: `@path` attaches the file as if Read ran. Covered below.
- **OpenCode**: `@path` in the TUI and in commands, `opencode run -f`, `instructions` in `opencode.json`. TODO.
- **Codex**: `AGENTS.md` and the initial prompt; `codex exec -i` attaches images only. TODO.

So foie_gras is one set of file lists plus a small adapter and test suite per agent.

## Lists

Lists live in `.foie_gras/` in the project root, one file per list. `/feed` loads `default`; any other list `NAME` gets its own `/feed-NAME`. A project with a single list can use a plain `.foie_gras` file instead.

Each line is a path, a glob (`**` works) or a directory; lines starting with `#` are comments.

```
# .foie_gras/auth
src/auth/**/*.py
docs/auth.md
tests/test_login.py
```

## Claude Code

Tested on 2.1.296.

### Install

```sh
mkdir -p .claude/skills
cp -r claude/skills/feed .claude/skills/
.claude/skills/feed/feed.sh --sync
```

`--sync` creates a `/feed-NAME` skill next to `feed` for every named list. Run it again after adding or removing a list; editing a list needs nothing. Install into `~/.claude/skills/` instead to get `/feed` in every project.

### Use

| You type | Result |
|-|-|
| `/feed <prompt>` | the default list is attached to your prompt, in one turn |
| `/feed-auth <prompt>` | the same with `.foie_gras/auth` |
| `/feed` | only attaches; Claude answers `Ready.` |
| `claude "/feed <prompt>"` | the same, straight from the shell |

Nothing is sent before you type.

### Is `/feed <prompt>` the same as typing `<prompt>`?

Almost. It's one turn in the same session, and Claude gets your text once, unchanged, in the command record Claude Code sends for every slash command. Besides that it gets the expanded skill (the `@path` lines and one instruction line) and the attached files.

One difference: `@path` inside a `/feed` prompt is not attached, because Claude Code expands `@` only in skill content, not in command arguments. Put the file in the list, or let Claude read it. Pasted images are untested.

### How it works

- `feed.sh` turns a list into `@path` lines. The skill injects them with `` !`feed.sh` ``, and Claude Code expands each one like a typed `@path`: the file is attached in Read result format and counts as read.
- `<!-- $second -->` keeps your prompt from appearing twice. A skill whose content uses no argument placeholder gets `ARGUMENTS: <prompt>` appended, which duplicates the command record. The named placeholder counts as used even when it expands to nothing. `$ARGUMENTS`, `$0` and `$1` all repeat the prompt in some cases: `$0` swallows it whole if the first word has an apostrophe.
- `--sync` copies `SKILL.md` once per named list, with the list name baked into the `feed.sh` call. Prompt text never reaches the shell: Claude Code pastes skill arguments into `!` commands unquoted, so a `/feed NAME <prompt>` form would break on the first apostrophe.

### Why not CLAUDE.md imports or hooks

`tests/claude.py`, Claude Code 2.1.296. Every mechanism below puts the content in context.

| Mechanism | Counts as read¹ | Prompt copies² | Re-reads³: Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|-|-|-|-|-|-|
| nothing | – | 1 | 2 | 2 | 2 |
| `@path` lines in CLAUDE.md | no | 1 | 1.2 | 0 | 2 |
| same + "do not Read them again" | no | 1 | 1.2 | 0 | 0 |
| SessionStart `additionalContext` | no | 1 | 2 | 2 | 2 |
| `--append-system-prompt` | no | 1 | 1.2 | 2 | 1 |
| `--resume --fork-session` of a fed session | no | 1 | 1.8 | 0 | 0 |
| `@path` in the prompt | yes | 1 | 2 | 0 | 0 |
| SessionStart `initialUserMessage` (`-p` only) | yes | 1 | 2 | 0 | 0 |
| command or skill with `@path` lines and `$ARGUMENTS` | yes | 2 | 0.5–0.8 | 0 | 0 |
| **`/feed` skill** | yes | 1 | 0 | 0 | 0 |

¹ Edit succeeds with the Read tool unavailable (`--strict`), which makes every model enforce read-before-edit.
² How many times your prompt text reaches Claude.
³ Read/Grep/Glob/Bash calls for "edit one fed file, quote another". Mean of 4 runs for Haiku, 1–3 for Sonnet/Opus.

5.5 models may Edit a file they haven't read when Read is available and wouldn't prompt, so "counts as read" only matters for permission-gated paths and partial reads. In practice the question is whether the model trusts what it was given: attachments look like Read results, and the skill's "count as read" line gets Haiku there too.

CLAUDE.md imports with that line are a zero-setup option for Sonnet/Opus. But they load in every session and every subagent, and don't count as read.

An agent's `initialPrompt: /feed` would run `/feed` automatically at startup, but it sends a turn before you type, so foie_gras doesn't use it.

### Limits

- A file over 25k tokens is silently skipped, not truncated. Raise `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`, e.g. `"env": {"CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS": "100000"}` in settings. Files over 256 KB are never attached.
- The skill needs the Bash tool, and its `!` command must be pre-approved; `allowed-tools` does that for `feed.sh`. Denying `Bash` or setting `disableSkillShellExecution` breaks it; fall back to plain `@path` lines in `SKILL.md`.
- Fed files stay in context for the rest of the session; keep lists task-sized.

## Tests

```sh
python3 tests/claude.py                          # re-reads, Sonnet, all mechanisms
python3 tests/claude.py --model opus --repeat 3
python3 tests/claude.py --strict --model haiku   # verdicts on context, read and prompt copies; exit 1 on mismatch
python3 tests/claude.py --strict --model haiku adapter_large adapter_large_raised
python3 tests/claude_tui.py                      # types /feed <task> into a real interactive session
python3 tests/claude_tui.py example              # the same in example/, with your settings
```

Each run uses a throwaway git repo and purges its Claude Code state afterwards. User settings and MCP servers are skipped. `claude_tui.py` checks that nothing is sent before it types, and accepts the trust dialog only for its own temp dir. The `example` scenario runs in place with your user settings and deletes its transcript. Per mechanism a run costs about $0.002 on Haiku, $0.03 on Sonnet and $0.06 on Opus.
