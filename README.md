# MCP Server for Sandboxed Python Code Execution

This MCP server allows your LLM to execute python code securely and returns the results - including files.
The code is executed in a configurable sandboxed environment, with strong defaults - like no network access and heavily
limited file write permissions.

It's great for use cases complicated use cases where LLMs run into hallucination. For example, stuff that requires a lot
of math - where LLMs are notoriously finicky - or if you want to generate cool graphs.
If you this, your LLM will always be able to count the number of "r" in strawberry!

## Quick Start

### MCP - via Docker (recommended)

For this to run we have to set some security options on the container.
This is due to bubblewrap needing to create user, mount and pid namespaces, which the container has to be allowed to do:
- seccomp=unconfined
- apparmor=unconfined
- systempaths=unconfined

This is mandatory - to my knowledge these are the miniumum needed permissions, but feel free to experiment :)

```
docker run -p 6400:6400 \
  --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined \
  -e PYTHON_DEPENDENCIES="pydantic numpy" \
  kigstn/mcp-run-isolated-python
```

You can pass your CLI settings directly after that, the dockerfile uses entrypoint to start the server and listens to all args.

Note:

- If you are running on Ubuntu 24 you will need to adapt your apparmor profile. We have a script, just run `setup_host.sh`. [More Info](https://github.com/anthropics/sandbox-runtime/blob/main/.github/workflows/integration-tests.yml#L152)
- These three options only loosen the *container*. The code your LLM runs is still sandboxed by `srt` inside it -
  no network, no writes outside its temp dir, own pid namespace.
- Docker automatically creates a separate UV python interpreter for the runtime - so you dont have to pass that :)
- To control your packages, use the env var `PYTHON_DEPENDENCIES` (space separated list). For greater control you need to build the image yourself
- We provide a sample docker-compose file, which you can use to run the server with a single command. Just adapt the env vars to your needs.

#### Configuration

To configure what packages are available to the LLM set `PYTHON_DEPENDENCIES` as an env var (space seperated list).

```
docker run ... -e PYTHON_DEPENDENCIES="numpy pandas" kigstn/mcp-run-isolated-python
```

Or bake your own image on top, which is better if you restart often, deploy offline, or want a pinned set:

```dockerfile
FROM kigstn/mcp-run-isolated-python
RUN uv pip install --python /sandbox/.venv/bin/python numpy pandas
```

---

Build args, if you build the image yourself:
- `ENVIROMENT` - Default: "trixie-slim"
- `PYTHON_VERSION` - Default: "3.13"
- `PYTHON_DEPENDENCIES` - Default: "pydantic" (space separated list)

Consult the Dockerfile for detailed info

### MCP - via direct hosting

`pip install mcp-run-isolated-python`

Then, just run the command to start the server:
`mcp-run-isolated-python`

### As a python package

This approached is generally discouraged for any production use, as it removes a lot of this projects security features. 

TBH - it should be fine, as this is used by procts such claude code in production on your PC.
Just be warned :)

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

When using the library like this, it will use your current python interpreter and environment, so you will have to make sure that the packages you need are installed there.

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
