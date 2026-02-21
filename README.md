# MCP Server for Sandboxed Python Code Execution

This MCP server allows your LLM to execute python code securely and returns the results - including files.
The code is executed in a configurable sandboxed environment, with strong defaults - like no network access and heavily
limited file write permissions.

It's great for use cases complicated use cases where LLMs run into hallucination. For example, stuff that requires a lot
of math - where LLMs are notoriously finicky - or if you want to generate cool graphs.
If you this, your LLM will always be able to count the number of "r" in strawberry!

## Quick Start

### MCP - via Docker (recommended)

WIP - support is suboptimal, as the anthropic sandbox runtime does currently only run in privileged docker running
configs.
Waiting on them to add proper support for containers, the existing options does not seem to do anything :D

If you still want to use it, here is the command:
`docker run --privileged .`

You can pass your CLI settings directly after that, the dockerfile uses entrypoint to start the server and listens to
all args.

Note:

- Docker automatically creates a separate UV python interpreter for the runtime - so you dont have to pass that :)
- To control your python version & packages, use the docker build args `PYTHON_VERSION` and `PYTHON_DEPENDENCIES` (space
  separated list)

### MCP - via direct hosting

`pip install mcp-run-isolated-python`

Then, just run the command to start the server:
`mcp-run-isolated-python`

### As a python package

This approached is generally discouraged for any production use, as it removes a lot of this projects security features.

But if you like to live dangerously, or you are the only one using this, or you are building a super quick prototype - this will be fine & should be safe, as it is still using sandboxed code execution.

```py
from mcp_run_isolated_python import CodeSandbox, CodeSandboxSettings

settings = CodeSandboxSettings(...)

# sync use
with CodeSandbox(settings=settings) as sandbox:
    result = sandbox.eval("print(1 + 1)")
    print(result)
    
# async use
async with CodeSandbox(settings=settings) as sandbox:
    result = await sandbox.eval("print(1 + 1)")
    print(result)
```

---

## Why this tool?

I built this out of frustration with the existing ecosystem.
Most of the existing tools do not set focus on security, which is a no-go if you are living in an enterprise environment
or want to use this for more than a single user on your own computer.

## Security Considerations

This tool was designed great focus on security - after all, giving an LLM unchecked access to a code executor is quite
risky.
To harden security, it is heavily recommended to use this server in an isolated container, like docker.

### Security Features

- Use of `srt`, a shell sandbox build by anthropic to limit LLM access, more
  info [here](https://github.com/anthropic-experimental/sandbox-runtime)
    - Remove network access
    - Remove write access to any non-allowed folders
    - Remove read access to specified folders
    - Restrict access to unix sockets
- Use of docker to isolate the host system from the system where the code is executed
- Removal of any env variables for the LLM process

### Open security concerns

- Reading of file contents on host system - needs to be restricted on case by case basis using the srt settings

## Comparison to (some) other tools

There really are too many to count.
I am not including most here, as most simply do not care about sandboxing at all.

Here is what I find to be the most relevant ones with a focus on security.

| Name                                                                              | Strong Sandboxing | Open Source & Selfhostable | Maintained | Released | Full python & package support | File output support |
|-----------------------------------------------------------------------------------|-------------------|----------------------------|------------|----------|-------------------------------|---------------------|
| [This Project](https://github.com/Kigstn/mcp-run-isolated-python)                 | ✅                 | ✅                          | ✅          | ✅        | ✅                             | ✅                   |
| [Monty](https://github.com/pydantic/monty)                                        | ✅                 | ✅                          | ✅          | ❌        | ❌                             | ❌                   |
| [Pydantic MCP Server](https://github.com/pydantic/mcp-run-python)                 | ✅                 | ✅                          | ❌          | ❌        | ❌                             | ❌                   |
| [Sandboxing Service, like Daytona ](https://daytona.io/)                          | ✅                 | ❌                          | ✅          | ❌        | ✅                             | ✅                   |
| [Build-In, like for Gemini](https://ai.google.dev/gemini-api/docs/code-execution) | ✅                 | ❌                          | ✅          | ❌        | ❌                             | ✅                   |
