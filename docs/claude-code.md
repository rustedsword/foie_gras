# Claude Code

How the Claude Code adapter works, and how it compares to the other ways of getting files into context. Tested on Claude Code 2.1.296.

## How it works

- `.claude/skills/foie-gras/` is a mod: a plugin folder with a hooks module, `hooks/register.ts`. Claude Code loads plugins from a project's skills folder once the workspace is trusted. It has no `SKILL.md`, so it adds no skill or slash command.
- Its `prompt.submit` hook takes `feed: <prompt>` or `feed:NAME <prompt>`, runs `files.sh NAME` to resolve the list, and passes `<prompt>` on without the prefix. A prompt that only starts with the word "feed" is left alone.
- Its `turn.step` hook answers the turn's first model request itself, with Read calls for those files and no model call. Claude Code runs them with its Read tool, records them as Claude's calls, and sends the model your prompt, the calls and their results. Claude continues as if it had read the files: they count as read, and nothing is left to reread.
- An error (no list, an entry that matches nothing, an empty list) drops the prompt and shows the message. So does `feed:` without a prompt. Claude Code puts the prompt back in the box for a retry, and nothing of it is kept in the session.
- Subagents, later steps of a turn and other prompts are untouched.
- `files.sh` takes the same list syntax as the Codex hook: paths, globs with `**`, directories, `#` comments, and a plain `.foie_gras` file as the default list. It searches the working directory and its parents for `.foie_gras`, stopping at a Git repository boundary.

## What Claude sees

For `feed: Fix the login bug`, the first request carries Claude Code's usual reminders and:

```
user       Fix the login bug
assistant  Read src/auth.py, Read tests/test_auth.py
user       the two Read results
```

There are no instructions, and the prompt is sent once. The transcript shows the Read calls like any of Claude's.

Claude takes those reads for its own choices. Asked why it read a file, it calls the read a mistake or makes up a reason. A line in the prompt naming the files ("Prefilling the context with important project files: …") lets it explain them, but stays in the prompt; the same reason in Claude's own voice, in hook context or on each Read result didn't help.

Claude Code requests adaptive thinking, which accepts a model turn without a thinking block; the mod's turn has none.

## Why Read calls

Measured with `tests/claude.py`. Every mechanism below puts the content in context.

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
| skill with `@path` lines, its text and record removed by a mod | yes | 1 | 1.75 | 0 | 0 |
| **foie_gras: Read calls opening the turn** | yes | 1 | 0 | 0 | 0 |

¹ Edit succeeds with the Read tool unavailable (`--strict`), which makes every model enforce read-before-edit. For foie_gras, `--strict` keeps the Read tool for the mod's calls and blocks Claude's own reads.
² How many times your prompt text reaches Claude.
³ Read/Grep/Glob/Bash calls Claude makes for "edit one fed file, quote another". Mean of 4 runs for Haiku, 1–3 for Sonnet/Opus; 8 for Haiku with the skill.

Attachments from `@` mentions reach Claude as text inside your message, formatted as Read results. Sonnet and Opus take them as read. Haiku says the contents "appeared in your message, not from a Read call I had made", and reads the files again, getting them in full. Read calls in Claude's own turn don't leave that doubt.

Other channels fall short:

- A skill always shows Claude its own text and the `/command` record, and adds `ARGUMENTS: <prompt>` unless an argument placeholder takes the prompt or a part of it.
- A `UserPromptSubmit` settings hook can add text, but past 10,000 characters Claude Code replaces it with a 2,000-character head and a file path. It also keeps nothing from a prompt the hook blocks or stops.
- Text a mod appends to the conversation is not a read, and keeping Claude from rereading it takes an instruction.
- Mentions that a hook adds to a prompt are not attached: Claude Code resolves mentions before prompt hooks run.
- A `skill.prompt` hook could rewrite a skill's text, but Claude Code's built-in `cc-plugin-sec-default` plugin skips user plugins for that event on machines with managed settings and in Team and Enterprise organizations.

An agent's `initialPrompt` would run at startup, but it sends a turn before you type, so foie_gras doesn't use it.

## Limits

- The mod API is early access in Claude Code 2.1.296 and may change between releases.
- Claude Code skips the mod until you trust the workspace; after accepting the trust dialog, restart or run `/reload-plugins`.
- Read's limits apply. A file over 25k tokens comes back as an error, and Claude reads it in parts; raise `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`, e.g. `"env": {"CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS": "100000"}` in settings. Reading a file outside the project asks for permission, as Claude's own Read would.
- PreToolUse hooks see the mod's Read calls; their `tool_use_id` starts with `toolu_foiegras`.
- `feed:` is refused while Claude is working; send it once the turn has finished.
- Fed files stay in context for the rest of the session, until compaction; keep lists task-sized.

## Tests

```sh
python3 tests/test_install.py                    # the built foie-gras in a throwaway git repo, no agents
python3 tests/claude_mock.py                     # real Claude Code requests against a local mock API, no inference
python3 tests/claude_tui.py                      # types feed: <task> into a real interactive session
python3 tests/claude_tui.py example              # the same in example/, with your settings
python3 tests/claude.py                          # re-reads, Sonnet, all mechanisms
python3 tests/claude.py --model opus --repeat 3
python3 tests/claude.py --strict --model haiku   # verdicts on context, read and prompt copies; exit 1 on mismatch
python3 tests/claude.py --strict --model haiku adapter_large adapter_large_raised
```

Each run uses a throwaway git repo and purges its Claude Code state afterwards. User settings and MCP servers are skipped. `claude.py` and `claude_mock.py`'s `-p` runs load the mod with `--plugin-dir`, because a throwaway directory is not a trusted workspace. `claude_tui.py` and `claude_mock.py interactive` check that nothing is sent before they type, and accept the trust dialog only for their own temp dir, so the mod loads as installed. The `example` scenario runs in place with your user settings and deletes its transcript. Per mechanism a run costs about $0.002 on Haiku, $0.03 on Sonnet and $0.06 on Opus.
