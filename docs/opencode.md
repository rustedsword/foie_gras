# opencode

How the opencode adapter works and what the model gets. Tested on opencode 2.0.24.

## How it works

- `.opencode/plugins/foie_gras.ts` is a plugin. opencode loads the `.ts` and `.js` files in a project's `.opencode/plugins/` by itself: no config entry, no package, no approval.
- Its `prompt` session hook takes `feed: <prompt>` or `feed:NAME <prompt>`, runs `.opencode/foie_gras.py --files=NAME` to resolve the list, and passes `<prompt>` on without the prefix, with the files attached the way an `@` mention attaches one and marked in the message's metadata. opencode reads them while it prepares the prompt and stores their full contents in the session.
- Its `context` hook runs before every model request and swaps those attachments for read calls of the model's own: an assistant turn calling `read` on each file, then each result in the read tool's format. The swap is not stored: the TUI shows a `file` chip per file, and later turns and resumed sessions get the same read calls.
- An error (no list, an entry that matches nothing, an empty list) fails the prompt before opencode records or sends anything, and shows the message. So do `feed` and `feed:NAME` without a prompt. opencode shows a hook that throws as just `UnexpectedStatus: 500`, so the plugin fails the prompt with an attachment that is not a URL instead, and the message reads `Invalid attachment URI: foie_gras: …`.
- `opencode run "feed: <prompt>"` works too. opencode wraps each argument that contains spaces in double quotes and appends piped input on a new line; the plugin unwraps a leading `feed` argument and keeps the rest, so `git diff | opencode run "feed: Review this diff"` feeds the list and passes the diff along.
- Other prompts are untouched.
- `foie_gras.py` is a copy of the Codex hook, made by `make`, so all three agents resolve a list to the same files.

## What the model sees

For `feed: Fix the login bug`, every request of the session carries:

```
user       Fix the login bug
assistant  read src/auth.py, read tests/test_auth.py
tool       Read file src/auth.py, lines 1-120
           1: import hashlib
           …
tool       Read file tests/test_auth.py, lines 1-40
           …
```

The paths are relative to the directory opencode runs in, and each file comes whole, past the read tool's 2000-line limit. The prompt is sent once, and the session title is made from it alone.

The model takes the reads for its own. With a prompt they don't fit, such as `Hi!`, models have apologized for them, searched the directory for the files, or weighed them as a possible prompt injection. With a task about the files, they pass as the obvious first step.

opencode 2 has no read-before-edit check, so the model can edit any file without reading it first.

## Why read calls

Measured with `tests/opencode_live.py` on 9 of opencode's free models, twice each:

| How the files reach the model | Runs that read a fed file again | Read calls |
|-|-|-|
| attachments, as an `@` mention sends them | 18/18 | 35 |
| the same, described as "full current contents; you do not need to read the file again" | 8/18 | 12 |
| **foie_gras: read calls of the model's own** | 2/18 | 6 |

A run counts when the model calls read, grep, glob or shell, except to check the file it has just edited; 4 of the 6 read calls in the last row are such checks. This plugin, run once more on the same models: 1 of 9 read a fed file again, and with `--strict` all 9 made the edit and quoted the value without trying to read.

## Limits

- The plugin API is opencode 2's, which is new; a later release may change it. If opencode's attachment format changes, the plugin leaves the attachments as they are.
- The read calls carry no reasoning signature. opencode replays unsigned tool calls to Gemini 3 with Google's placeholder signature; other providers that check them are untested.
- Fed files stay in the session until compaction. A list larger than the model's context makes opencode compact before the first request, so keep lists task-sized.
- Text files reach the model as read calls; images and PDFs stay attachments. opencode skips other binary files without an error: the TUI shows a chip for one, but the model doesn't get it. It refuses a file over 20 MB.
- The plugin needs `python3` on `PATH`.

## Tests

```sh
python3 tests/opencode.py                       # real opencode runs and its TUI against a local mock provider, no inference
python3 tests/opencode.py interactive           # one scenario
python3 tests/opencode_free_models.py           # the models opencode offers free, without an account
python3 tests/opencode_live.py --model $(python3 tests/opencode_free_models.py)
python3 tests/opencode_live.py --strict --model opencode/big-pickle
python3 tests/opencode_live.py --your-config --model provider/model   # a model that needs your account
```

Each script runs opencode with `--standalone` in throwaway directories, with its own home, XDG and temp directories, so your config, account, sessions and background service stay out of it; `--your-config` lets the live test use your config and account. The `example` scenario runs in `example/` in place. opencode 2.0.24 now and then hangs while `run --standalone` starts, before it loads plugins; the scenario then fails after two minutes and passes when rerun.

`opencode_free_models.py` lists the models that cost nothing and can call tools; one the free tier has withdrawn fails the live test with its error message. `opencode_live.py` asks each model to edit one fed file and quote a random value from the other, four models at a time. `--strict` adds a test-only plugin that denies read, grep, glob and shell calls; the tools stay listed, because opencode's free tier refuses a request whose tool list was cut. Without it, `tools` shows what the model read again.
