# Architecture — mcp-run-isolated-python @ a80b830 (worktree content-identical to HEAD; untracked .DS_Store)

## Product, principals, resources
An MCP server (FastMCP 4.0.3, mcp 2.2.0) exposing one tool, `run_python_code`, which executes caller-supplied Python inside Anthropic's `srt` sandbox-runtime and returns stdout/stderr plus every file the code writes to `./output` (src/mcp_run_isolated_python/mcp_server.py:26-42, code_executor.py:68-139). Also usable as a library (`CodeSandbox`, direct_use.py). README claims: "execute python code securely", "no network, no writes outside its temp dir, own pid namespace", "Removal of any env variables for the LLM process", "Remove read access to specified folders", intended for enterprise / multi-user (README.md:3-5,37-38,104-122); README:126 admits host file reads must be restricted case by case via srt settings.
- Lower-trust principals: (1) any MCP HTTP client able to reach the port — no auth; (2) the LLM, possibly prompt-injected, choosing code; (3) the sandboxed code itself (untrusted by design).
- Trusted: operator (CLI flags, env PYTHON_DEPENDENCIES, srt settings file, Docker build args); library caller.
- Protected resources: host/container filesystem outside the per-run dir, server-process files and environment, other concurrent runs' code/output, server availability, the host behind the container.

## Comparable baseline
README cites pydantic mcp-run-python (Pyodide/Deno), Daytona, Gemini code execution. Isolation primitive is srt (bubblewrap on Linux, Seatbelt on macOS). Comparable code-exec sandboxes treat sandbox→host data flows (file return channels) as part of the boundary.

## Stack and deployment paths
Python >=3.10, uv/hatchling, cyclopts CLI, structlog, filetype 1.2.0. Deployment modes:
- CLI on host: server and code run as the invoking user (user=None), bind localhost:6400/mcp, working dir = cwd, settings ./default_srt_settings.json (cli.py:16-145).
- Docker (Dockerfile, docker-entrypoint.sh, docker-compose.yml): no USER line → server runs as root; code runs as `nonroot` (uid 999) via `subprocess.run(user=)`; `--mcp_host=0.0.0.0`; port 6400 published; Dockerfile:36 sets `enableWeakerNestedSandbox: true`; compose sets seccomp/apparmor/systempaths unconfined; /code and /sandbox chowned to nonroot; entrypoint runs `uv pip install ${PYTHON_DEPENDENCIES}` as root.
- Library: caller-supplied CodeSandboxSettings.
Offline limits: tests need `srt`; `docker build`, `uv sync`, npm/apt installs, publish are prohibited (network). Local image `mcp-run-isolated-python-mcp-run-isolated-python:latest` (built 2026-09-10, arm64, fastmcp 4.0.3) exists; parent sandbox launcher `sbx.py` runs it with no network, read-only rootfs, scratch-only writes, empty env allowlist, resource and 120s wall limits, current source via PYTHONPATH=/target/src; `--srt` mode runs the real srt+bwrap as in the Docker deployment (verified: srt works, code runs as uid 999).

## Entry surfaces and key paths
1. MCP tool arg `python_code` → `_make_run_dir("output")` creates `<workdir>/<uuid4>/` and `output/` (path-based mkdir + chown to settings.user) → code written to `code.py` → cmd = `ulimit -u 256 2>/dev/null; ulimit -f 97656 2>/dev/null; exec [unshare --ipc --user --map-current-user ]"<py>" "<code.py>"` (unshare prefix only when sys.platform=="linux" and `unshare` on PATH) (code_executor.py:241-250) → `_run_sandboxed`: `Popen(("srt","--settings",<per-process temp settings>,"-c",cmd), cwd=run dir, stdin=DEVNULL, env={PATH, CLAUDE_CODE_TMPDIR=<run dir>}, user=, start_new_session=True)`; two daemon threads drain stdout/stderr keeping ≤1,000,001 bytes each; `proc.wait(timeout)`; on timeout `os.killpg(proc.pid, SIGKILL)` (inner bwrap relies on `--die-with-parent`); readers joined with 5 s timeout; output decoded `errors="replace"`, truncated at 1 MB, logged at INFO (138-178) → `_collect_output_files`: `os.open(output, O_DIRECTORY|O_NOFOLLOW)`, `os.listdir(dir_fd)`, each entry `os.open(name, O_NOFOLLOW|O_NONBLOCK, dir_fd)`, fstat requires S_ISREG and st_nlink==1, reads ≤100,000,001 bytes, skips a file >100 MB or one that would push the cumulative total past 200 MB (no cap on entry count); `filetype.guess(data)` → Image/Audio/File content (base64) returned (180-222) → `finally: _remove_run_dir(code_path)`: chmod run dir 0700, top-down `os.walk` chmod'ing every non-symlink subdir 0700 (path-based `Path.chmod`, follows symlinks; is_symlink check then chmod is a check/use pair), then `shutil.rmtree(ignore_errors=True)`, logs error if still present (59-71, 264-267). Exceptions return `traceback.format_exc()` to the client (255-263). Code logged at INFO (240).
2. Per-process srt settings (`_write_srt_settings`, 89-111): base settings + `denyRead += [working_directory.resolve()]`, `allowRead += ["."]`, `denyWrite += ["/tmp/claude", "/private/tmp/claude", <home of settings.user or server>/.npm/_logs, <home>/.claude/debug]` (home via `pwd.getpwnam(user)`), written once via `tempfile.mkstemp`, chmod 0644, reused for every run. Whether srt <=0.0.64 honours allowRead, denyWrite over its own implicit write paths, and CLAUDE_CODE_TMPDIR is runtime behaviour to verify.
3. Library `CodeSandbox.eval` → same executor (direct_use.py).
4. MCP HTTP transport: unchanged since run-1 — `mcp.run_async(...)` with no auth/Host guard (mcp_server.py:49-56); owner accepted the run-1 finding as operator responsibility.
5. Operator inputs → shell strings (cli.py, mcp_server.py:21-23, docker-entrypoint.sh) — unchanged.
6. CI publish.yml — unchanged.

## Changes since run-2 (commit a80b830, fixes for run-2 findings)
- `stdin=subprocess.DEVNULL` on the pre-check and every sandbox Popen (run-2 popen-inherits-server-stdin).
- Cumulative 200 MB bound on returned output files (run-2 no-aggregate-output-file-bound).
- Per-run shell `ulimit -u 256` (RLIMIT_NPROC — counted per real uid, so shared by all concurrent runs of the same uid and, in CLI mode, by the host user) and `ulimit -f` ~100 MB; docker-compose.yml adds container `pids_limit: 512`, `mem_limit: 2g`, `cpus: 2` (run-2 no-per-run-resource-limits). Compose limits apply only when deployed with this compose file.
- Linux: `unshare --ipc --user --map-current-user` wraps the interpreter inside srt/bwrap: fresh IPC namespace AND a fresh user namespace in which sandboxed code holds a full capability set (run-2 srt-bwrap-no-ipc-namespace-shared-across-runs). New privilege surface to review.
- denyWrite for srt's implicit write paths + CLAUDE_CODE_TMPDIR=<run dir> (run-2 srt-default-write-paths-shared-across-runs).
- `_remove_run_dir` unlock-then-rmtree (run-2 rmtree-ignore-errors-sandbox-locked-dir).
Revalidate each fix for completeness (variants, parallel paths, platform differences, per-uid vs per-run accounting, whether srt honours the new settings), and review the new user-namespace and chmod-walk surfaces.

## Starting paths
src/mcp_run_isolated_python/code_executor.py, mcp_server.py, direct_use.py, cli.py, utils/settings.py, utils/logger.py, default_srt_settings.json, Dockerfile, docker-entrypoint.sh, docker-compose.yml, .github/workflows/publish.yml, .github/actions/setup_python_environment/action.yaml, tests/unit/**.

## Prior coverage
run-1 (@d099ead) and run-2 (@5d3b260), both standard, whole repo. run-2: 7 confirmed, 1 needs_validation, 1 rejected. Six run-2 confirmed findings target code changed in a80b830 → changed-source revalidation units (not excluded from hunting). HTTP no-auth/Host-guard finding (mcp_server.py, cli.py, entrypoint unchanged; owner accepted as operator responsibility) → carried same-source to Phase 3 re-verification and excluded from hunting. run-2 needs_validation (macOS descendants outlive run) → current work on changed source. run-2 rejected Seatbelt POSIX-IPC claim: suppresses only that exact claim. Units covered on unchanged source (CLI operator input, CI publish, repo obvious things) → visible, lower priority re-pass. New unit: in-sandbox user namespace from the unshare wrapper.

## Companion selection
- ATTACK-CLASSES.md (ordinary): Resource and file handling, Access control, Feature abuse and data leakage, Injection, Chained vulnerabilities and trust boundaries, Wildcard, Obvious things.
- AI-AND-LLM.md: MCP server executing model-chosen code; model/client-controlled tool args drive a code-exec sink and output channel.
- DESKTOP-MOBILE-AND-LOCAL-IPC.md: server is a (root in Docker) helper consuming files produced by a lower-privilege sandboxed process (privileged helper confused deputy, local file ownership/TOCTOU).
- RESOURCE-EXHAUSTION-AND-AVAILABILITY.md: timeouts, cleanup failure, unbounded output, shared worker threads.
- CLOUD-AND-DEPLOYMENT.md: Docker image/compose define runtime identity, capabilities, reachability.
- WEB-PROTOCOL-AND-AUTH.md: HTTP transport Host-header/DNS-rebinding trust for a localhost-bound unauthenticated server.
- SUPPLY-CHAIN-AND-RELEASE.md: CI publish workflow and mutable build inputs.
- Excluded: CLIENT-SIDE (no browser code), DATA-ISOLATION-AND-LIFECYCLE (no persistent/multi-tenant data store), MEMORY-SAFETY-AND-BINARY (pure Python), PROTOCOLS-RPC-AND-MESSAGING (JSON-RPC framing/routing entirely inside FastMCP; single tool, no custom dispatch).
