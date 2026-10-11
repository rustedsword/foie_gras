# Codex CLI

Use Codex normally. A `UserPromptSubmit` hook reads the files in
`.foie_gras/default` and supplies their complete contents with your first prompt,
before the model runs. Submit `feed:NAME` alone to load another list or refresh
one already loaded, then enter your task normally.

## Setup

From your project directory:

```sh
python3 /path/to/foie_gras/codex/feed.py --install
codex
```

Review and trust the foie_gras hook when Codex asks, or open `/hooks`. This is
Codex's built-in review for local hooks. After that, type tasks in the ordinary
interactive session:

```text
Fix the login bug
```

On the first prompt, that loads `.foie_gras/default`. To load `.foie_gras/auth`,
submit this command by itself:

```text
feed:auth
```

The hook loads the files and stops that submission before a model call. Codex
shows a local message that the files are loaded. Now submit your task normally:

```text
Fix the login bug
```

The model receives the file contents and your task. It does not receive the
selector command, the local confirmation, or instructions about `feed:NAME`.
Codex's prompt hook can attach context or stop a submission, but cannot rewrite
the submitted text. For that reason, `feed:auth Fix the login bug` is rejected
locally with instructions to submit the command and task separately.

Ordinary follow-ups do not reload any files. Use `feed:default` to explicitly
reload the default list, or `feed:auth` to reload the named list. Every explicit
load reads fresh contents. If you start with `feed:auth`, that replaces
the automatic default preload. Adding or editing a list needs no sync or restart;
use `feed:NAME` to load it.

The hook checks Codex's transcript for an earlier preload, so resuming a session
does not reload files either. It needs no separate state file. Existing context
remains in the conversation until Codex compacts it; use `feed:NAME` if you want
to restore fresh file contents afterward. One-shot `codex exec --ephemeral`
runs have no transcript and load files with their single prompt.

Requires Python 3.10+ and a current Codex CLI with `UserPromptSubmit` hooks.
Tested with 0.162.1. Hooks are enabled by default; if you have explicitly disabled
them, enable `features.hooks` in your Codex configuration.

The installer adds one handler to the project's `.codex/hooks.json`, preserving
other hooks. It references this checkout's `codex/feed.py` by absolute path, so
keep the checkout at that location. Repeating installation at the same path is
safe. You can also supply a project path: `python3 codex/feed.py --install example`.
There are no skills, generated commands, or session launchers.

To remove the integration, remove its handler from `.codex/hooks.json`, or
disable it in `/hooks`. Leave any other hooks in place.

## Non-interactive use

With the project's hook installed and trusted, a normal `codex exec` request
loads the default files before sending the task to the model:

```sh
codex exec "Fix the login bug"
```

Choose another list with `FOIE_GRAS_LIST`:

```sh
FOIE_GRAS_LIST=auth codex exec "Fix the login bug"
```

The hook reads `.foie_gras/auth` and its files. Codex sends the complete contents
with your unchanged task in the first model request. No selector syntax or explanation
is added to the prompt. Missing or invalid lists block the task instead of
falling back to `default`.

This also works with a task read from stdin (`codex exec -`), with `--ephemeral`,
and with interactive `codex`. The variable chooses the initial preload only;
resuming an already preloaded session does not reload files. In interactive
sessions, a standalone `feed:NAME` command explicitly loads that list regardless
of the environment selection.

Do not use `codex exec "feed:auth"` to run a task: that command only loads context
locally and exits without calling the model. Use the environment variable and
your actual task for a single non-interactive run.

## File handling

The hook searches the session directory and its parents for `.foie_gras`,
stopping at a Git repository boundary. Paths in a manifest are relative to its
directory; file labels sent to Codex are absolute, so starting in a subdirectory
works. A plain `.foie_gras` file also serves as the default list.

Each line is a file, glob (including `**`), or directory. Blank lines and comments
beginning with `#` are ignored. Directories include their files recursively,
including hidden files, without following nested directory symlinks. Spaces in
paths work, and duplicate files are loaded once.

Files must contain UTF-8 text. Missing matches, empty lists, binary files, and
read errors block the prompt with an explanation. If there is no `.foie_gras`,
ordinary prompts proceed unchanged; an explicit `feed:NAME` or `FOIE_GRAS_LIST`
selection reports an error.

The hook preserves complete contents and line endings, with file boundaries and
final-newline information. Its `additionalContextLimit: 0` setting prevents
Codex from replacing large hook output with a short preview. The model's context
window still applies. No separate turn or model tool call is needed to load files.

## Source verification and tests

The implementation was checked against the upstream Codex source at
[`cc7ba336`](https://github.com/openai/codex/tree/cc7ba33601286a751477832b01de7b6f8de0dd9c):

- [Prompt submission](https://github.com/openai/codex/blob/cc7ba33601286a751477832b01de7b6f8de0dd9c/codex-rs/core/src/hook_runtime.rs#L677)
  awaits `UserPromptSubmit` and records its context with the accepted user input.
- [Hook output handling](https://github.com/openai/codex/blob/cc7ba33601286a751477832b01de7b6f8de0dd9c/codex-rs/hooks/src/output_spill.rs#L65)
  passes all text through when the configured limit is zero.

See also the [official hooks documentation](https://learn.chatgpt.com/docs/hooks).

```sh
python3 tests/test_codex_feed.py
python3 tests/codex.py
python3 tests/codex_tui.py
python3 tests/codex_live.py --strict
```

The unit tests need only Python. The next two commands capture actual Codex
requests with a local mock provider, without model inference. They check default
and named lists, full large-file contents, and one copy of the task. The TUI test
reviews the installed hook through Codex's own UI, checks that ordinary
follow-ups add no file contents, and verifies explicit refreshes and list
changes in the same session. It checks that selector commands make no model
request and stay out of subsequent requests, including title generation. It also
checks that an old-style inline selector and task are rejected without reaching
the model. The TUI test requires Linux and bubblewrap
(`bwrap`) to isolate Codex state without changing your configuration.

The live test uses your Codex account in a temporary fixture. It preloads two
files with random values, asks Codex to edit one and report the value in the
other, and blocks file-reading tools with a test-only guard. The verified result:

```json
{"strict": true, "edit": true, "context": true, "tools": ["apply_patch"], "ok": true}
```

Add `--keep` to integration tests to retain fixtures and logs. The live test also
accepts `--model MODEL`. During normal work, the model can still choose to read
files, for example to inspect additional files outside the selected list.
