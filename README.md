# foie_gras: force-feed files to your agent

You ask an agent to fix a bug, then wait while it searches the repo and reads files you already knew it would need. Open a new session, and it does the same thing again.

Define a list of files, and foie_gras loads their contents into the model's context before it gets your first prompt. Unlike listing paths in `AGENTS.md` or `CLAUDE.md`, this ensures the model can't refuse or "forget" to load them.

Works with Claude Code and Codex CLI.

## Use

Run the [`foie-gras`](foie-gras) script on your git repository. You'll need Python 3.10+:

```sh
./foie-gras path/to/repo
```

Add some paths to `path/to/repo/.foie_gras/default`:

```
src/auth/**/*.py
docs/auth.md
tests/test_login.py
```

Then go to your repo and run your harness as usual. (You might need to approve some stuff)

## Codex CLI

Send `feed` or `feed:<list_name>` as the first prompt. (It will not be sent)

Then enter your real prompt.

Or set `FOIE_GRAS_LIST` before starting Codex:

```sh
FOIE_GRAS_LIST=default codex
FOIE_GRAS_LIST=stuff codex exec "Kill all humans with this stuff"
```

## Claude Code

Type `feed: <your prompt>` or `feed:<list_name> <your prompt>`

or non-interactively:

`claude -p "feed: Launch a nuke"`

## Misc

The [Codex notes](docs/codex.md) and the [Claude Code notes](docs/claude-code.md) explain how it works, its limits, and the tests.
