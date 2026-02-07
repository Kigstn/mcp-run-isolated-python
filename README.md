# mcp-run-isolated-python

[//]: # (todo: name & description)
WIP and TODO :) 

---

## Installation

We are using `uv` to manage python packages and versions.

#### Steps

1. [Install `uv` however you prefer](https://docs.astral.sh/uv/getting-started/installation/)
2. Install packages -> `uv sync --all-extras`
3. Install prek (or pre-commit) -> `uv run prek install`

## Security Considerations

This tool was designed great focus on security - after all, giving an LLM unchecked access to a code executor is quite risky.
To harden security, it is heavily recommended to use this server in an isolated container, like docker.

### Security Features
- Use of `srt`, a shell sandbox build by anthropic to limit LLM access, more info [here](https://github.com/anthropic-experimental/sandbox-runtime)
  - Remove network access
  - Remove write access to any non-allowed folders
  - Remove read access to specified folders
  - Restrict access to unix sockets
- Use of docker to isolate the host system from the system where the code is executed
- Removal of any env variables for the LLM process

### Open security concerns
- Reading of file contents on host system - needs to be restricted on case by case basis using the srt settings
