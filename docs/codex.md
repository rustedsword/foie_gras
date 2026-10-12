# Codex CLI

Implementation notes and verification.

## Hook lifecycle

The adapter uses `UserPromptSubmit`, with `features.hooks` enabled. Tested with
Codex CLI 0.162.1.

A feed command returns the files in `hookSpecificOutput.additionalContext`,
alongside `continue: false` and a confirmation in `stopReason`. Codex records the
context, displays the confirmation, and completes the submission locally. The
next task reaches the model together with the recorded context.

For an environment-selected preload, the hook scans the transcript for a
developer message starting with `foie_gras: current files from list `. That
record marks the session as preloaded across resume and compaction. Fed context
remains in the conversation until Codex compacts it.

The handler in `.codex/hooks.json` resolves `.codex/foie_gras.py` from the Git
root. The installer identifies its handler by `statusMessage` and updates it in
place. For adapter development, `python3 codex/feed.py --install path/to/project`
points a project's handler at this checkout. Manage the handler through `/hooks`
or `.codex/hooks.json`.

## File handling

The hook searches the session directory and its parents for `.foie_gras`,
stopping at a Git repository boundary. Relative entries resolve from the
directory containing `.foie_gras`; file labels sent to Codex are absolute.

Recursive directory expansion includes hidden files. Resolved paths identify
duplicate files, which are loaded once.

The Claude Code mod and the opencode plugin resolve lists with copies of this
script, run with `--files=NAME`, so all three agents load the same files.

Files must contain UTF-8 text. Absent or empty lists, binary files, and read
errors produce a local error message and block the requested load.

The hook preserves complete contents and line endings, with file boundaries and
final-newline information. Its `additionalContextLimit: 0` setting passes the
complete output to the model. Selected contents must fit the model's context
window.

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
python3 tests/test_install.py
python3 tests/codex.py
python3 tests/codex_tui.py
python3 tests/codex_live.py --strict
```

The first two need Python, Git and make. The next two capture actual Codex
requests with a local mock provider. They verify command parsing, environment
selection, complete large-file contents, and one copy of the task. The TUI test
also reviews the hook through Codex's UI and exercises loading, refreshing, and
switching lists within a session. It requires Linux and bubblewrap (`bwrap`) for
an isolated Codex environment.

The live test uses your Codex account in a temporary fixture. It preloads two
files with random values, asks Codex to edit one and report the value in the
other, and blocks file-reading tools with a test-only guard. The verified result:

```json
{"strict": true, "edit": true, "context": true, "tools": ["apply_patch"], "ok": true}
```

Add `--keep` to integration tests to retain fixtures and logs. The live test also
accepts `--model MODEL`.
