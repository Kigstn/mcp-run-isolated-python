# Findings detail (confirmed medium and above)

## Per-run process caps are not sized against the shared container pid pool and there is no limit on concurrent runs, so two unauthenticated requests make other clients' runs fail (and runs still have no memory bound)

`code_executor.py:_run_sandboxed/no-per-run-resource-limits` — **medium**

Commit a80b830 added `ulimit -u 256` and `ulimit -f` in front of each sandboxed interpreter. The hunter said RLIMIT_NPROC is one pool per uid shared by all runs. That is refuted on Linux. The ulimit is applied just before `unshare --user` gives each run a new user namespace, and kernel ucounts (5.14 and later) then charge the limit per run. Verified under real srt+bwrap on kernel 6.8: an attacker run stopped at its own cap while a concurrent run of the same uid 999 still forked 10 children (agents/ver-limits/artifacts/evidence1.txt). The hunter's reproduction never reached the 256 cap. Its attacker stopped at 102 processes because it exhausted the fixture's 128-pid container cgroup. The underlying root cause is still present, though. Each run's cap is not sized against the shared container pid pool, and nothing limits how many runs execute at once. run_python_code runs in the framework thread pool with no semaphore or per-caller cap. Under the shipped compose file (pids_limit 512, 256 per run), two concurrent unauthenticated runs are enough to use up the pool. In any deployment whose container pid limit is at or below 256, one run is enough. After that, the server's own subprocess.Popen for another client's run fails with EAGAIN. The broad except turns this into 'Tool run failed. Do not call this tool again, inform the user that it is broken.' This was reproduced at scaled values: a per-run cap of 60 against a 128-pid pool, with two attacker runs and a concurrent victim run (agents/ver-limits/artifacts/evidence2.txt). The server process stays up. Service recovers once the attacker runs end (at most code_timeout_seconds, 30s by default), and resubmitting sustains the outage. The code comment says the cap exists to keep a fork bomb from starving the server. The server's ability to start runs is exactly what gets starved, so the owner's stated intent is not met. Runs also still have no memory bound (no ulimit -v, RLIMIT_AS or per-run cgroup). That part is source-visible only and was not reproduced here. It is contained only where a container memory limit exists. The README `docker run` command sets none, and there it can reach host memory. On macOS CLI mode the unshare wrapper is absent, so `ulimit -u` there counts against the host user's per-uid total. That was not verified.

### Trace and evidence

1. **entrypoint** `src/mcp_run_isolated_python/mcp_server.py:26` `run_mcp` — run_python_code is registered as an MCP tool over HTTP with no authentication (Docker binds 0.0.0.0:6400). Any client supplies python_code and can call it concurrently.
2. **propagation** `src/mcp_run_isolated_python/code_executor.py:242` `CodeExecutor.run_python_code` — The only limits are `ulimit -u 256` and `ulimit -f`. Because unshare --user follows (245-250), the process cap is per run on Linux, but nothing bounds the number of concurrent runs and there is no memory limit.
3. **propagation** `src/mcp_run_isolated_python/code_executor.py:139` `CodeExecutor._run_sandboxed` — Popen(srt ...) for every request with no admission control and no per-run cgroup. All runs share the container's pid and memory pools with the root server.
4. **sink** `src/mcp_run_isolated_python/code_executor.py:160` `CodeExecutor._run_sandboxed` — The attacker runs hold their processes until proc.wait(timeout) returns. A concurrent victim's Popen at :139 then fails with EAGAIN from the exhausted container pid cgroup. The except at :255 catches it and the client is told the tool is broken.

Evidence:
- `src/mcp_run_isolated_python/code_executor.py:36` — MAX_SANDBOX_PROCESSES = 256. The comment at line 35 says it keeps a fork bomb from starving the server and is 'shared by concurrent runs'. On Linux, with the unshare user namespace, it is actually per run (evidence1), and it is not sized against the container pid pool.
- `src/mcp_run_isolated_python/code_executor.py:243` — `ulimit -u 256; ulimit -f 97656` is the only per-run limit. There is no ulimit -v or RLIMIT_AS memory limit.
- `src/mcp_run_isolated_python/code_executor.py:246` — `unshare --ipc --user --map-current-user` runs after the ulimit, so RLIMIT_NPROC is charged per user namespace, i.e. per run (this refutes the hunter's 'per-uid shared pool' mechanism).
- `src/mcp_run_isolated_python/code_executor.py:139` — Popen has no preexec_fn, per-run cgroup or memory limit, and run_python_code has no semaphore or concurrency cap.
- `src/mcp_run_isolated_python/code_executor.py:255` — When the victim's server-side Popen raises BlockingIOError (EAGAIN), the broad except returns 'Tool run failed. Do not call this tool again... it is broken' with a traceback.
- `docker-compose.yml:10` — pids_limit: 512 (mem_limit 2g, cpus 2 on lines 11-12) is one container-wide pool. Two runs at 256 each fill it.
- `README.md:24` — The recommended `docker run` sets no --pids-limit and no --memory, so neither the number of concurrent runs nor per-run memory is bounded short of host limits.
- `docker-entrypoint.sh:14` — --user=nonroot: the server (root) forks every run in the same container pid cgroup the runs consume.

### Principals
- Attacker: An unauthenticated MCP client submits two concurrent fork-loop runs that exhaust the shared container pid pool. A different client's ordinary run submitted during that window fails. Reproduced through the library API in the project's Docker image under real srt 0.0.64 + bwrap, with the server as root and code as uid 999.
- Invariant: A run that hits its quota should fail only itself. The server must always keep headroom to start runs for other clients. Concretely: (per-run cap × maximum concurrent runs) + server overhead must stay below the container pid and memory limits, or each run must get its own cgroup (pids.max/memory.max). Extra runs beyond that are rejected or queued.

### Reproduction

Payloads:
```python
import os, time
n=0
try:
    while True:
        if os.fork()==0:
            time.sleep(12); os._exit(0)
        n+=1
except OSError as e:
    print('attacker forked', n, 'then', e)
time.sleep(11)
```
```python
import os, time
k=0
try:
    for i in range(10):
        if os.fork()==0:
            time.sleep(2); os._exit(0)
        k+=1
    print('victim forked', k)
except OSError as e:
    print('victim fork failed after', k, e)
```

Steps:
1. Run python3 sbx.py ver-limits --srt (no network, read-only rootfs, 512m memory, 128-pid limit, 1 cpu, kernel 6.8). Build CodeExecutor(CodeSandboxSettings(user='nonroot', path_to_srt_settings=/code/default_srt_settings.json, path_to_python_interpreter=/sandbox/.venv/bin/python, working_directory=/scratch/wdN, code_timeout_seconds=25)). Lower code_executor.MAX_SANDBOX_PROCESSES only so the cap-to-pool ratio fits the fixture; the code path is unchanged.
2. Per-run accounting check (cap 30): start one fork-loop run in a thread. 5s later, run the victim fork payload through the same executor.
3. Starvation check (cap 60 against the 128-pid pool, modelling 256 against compose's 512): start two fork-loop runs 0.5s apart. 4.5s later run the victim payload, then run print('recovered') after both attackers exit.

### Observed result
Per-run check (agents/ver-limits/artifacts/evidence1.txt): the attacker stopped at 27 forks with EAGAIN from its own cap of 30. The concurrent victim ran as uid 999 with Max processes 30 and forked all 10 children. So the cap is per run, not a per-uid pool. Starvation check (agents/ver-limits/artifacts/evidence2.txt): attacker 1 hit its own cap at 57 forks. Attacker 2 got 21 forks before EAGAIN from the container pid cgroup. The victim run returned status='failure', 'Tool run failed. Do not call this tool again, inform the user that it is broken.', with BlockingIOError [Errno 11] raised in the server's own subprocess.Popen. The run after the attack returned status='success', 'recovered'. The hunter's single-run result (102 forks, victim failed) came from the fixture's 128-pid cgroup being below the 256 cap.

### Conditions and containment

- *authentication_level*: No authentication: any client that can reach the MCP HTTP endpoint (Docker publishes 0.0.0.0:6400), or a prompt-injected LLM, can submit runs.
- *timing_dependency*: The victim's request must arrive while the attacker runs are active (up to code_timeout_seconds, 30s by default). The attacker resubmits to keep the window open.
- *system_configuration*: The number of attacker requests needed depends on the container pid limit. The shipped compose (pids_limit 512 against a 256-per-run cap) needs two concurrent runs. Any limit at or below 256 needs one. The README docker run sets no pids limit, so exhaustion there depends on host limits (not exercised). The memory impact depends on whether a container memory limit is set.
- *environmental_dependency*: Per-run NPROC accounting depends on Linux with the unshare wrapper and ucounts (kernel 5.14 or later; verified on 6.8). macOS CLI mode has no user namespace, so the cap counts per host uid there (not verified).

### Remediation and regression case

Bound the total, not only each run. (1) Add admission control in run_python_code: a process-wide BoundedSemaphore of MAX_CONCURRENT_RUNS, acquired without blocking; when full, return a 'busy, retry later' result instead of the 'tool is broken' message. (2) Size MAX_SANDBOX_PROCESSES so that MAX_CONCURRENT_RUNS × cap + srt/node/bwrap threads + server headroom stays below the container pids_limit. For example, 4 runs × 64 against 512. Keep the cap before `unshare --user` so it stays per run on Linux. (3) Add a per-run memory cap for the interpreter only (`ulimit -v`, not on srt/node), sized so that the concurrent runs together fit under mem_limit. (4) Document --pids-limit and --memory in the README `docker run` command. (5) Better long-term fix: a per-run cgroup (pids.max/memory.max) so the server's own forks never share a budget with sandboxed code. Regression test: with MAX_CONCURRENT_RUNS fork-loop runs active, one more run returns busy and does not raise in Popen, and a run submitted after they end succeeds.

`src/mcp_run_isolated_python/code_executor.py`:
```
# per-run process cap; MAX_CONCURRENT_RUNS * cap (+ srt/bwrap threads) must stay below the container pids_limit
MAX_SANDBOX_PROCESSES = 64
MAX_CONCURRENT_RUNS = 4
MAX_SANDBOX_MEMORY_KIB = 400_000  # MAX_CONCURRENT_RUNS * this < container mem_limit
_run_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)

# in run_python_code, before _make_run_dir:
if not _run_slots.acquire(blocking=False):
    return [CodeExecutionResult(status="failure", output="Too many concurrent runs, retry later.")]
try:
    ...
    limits = (
        f"ulimit -u {MAX_SANDBOX_PROCESSES} 2>/dev/null; ulimit -f {MAX_OUTPUT_FILE_BYTES // 1024} 2>/dev/null; "
        f"ulimit -v {MAX_SANDBOX_MEMORY_KIB} 2>/dev/null"
    )
    ...
finally:
    _run_slots.release()
```

`README.md`:
```
docker run -p 6400:6400 \
  --pids-limit 512 --memory 2g --cpus 2 \
  --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined \
  -e PYTHON_DEPENDENCIES="pydantic numpy" \
  kigstn/mcp-run-isolated-python
```

## Sandboxed code can make its run directory survive cleanup by creating a very deep directory tree (the a80b830 unlock-then-rmtree fix is incomplete)

`code_executor.run_python_code:rmtree-ignore-errors-sandbox-locked-dir` — **medium**

_remove_run_dir unlocks directories with a path-based os.walk and a Path.is_symlink()/Path.chmod pair, then calls shutil.rmtree(ignore_errors=True). The sandboxed code decides how deep the tree in its run dir goes. It can build it with dir_fd-relative mkdir, so no path limit applies while it writes. Once a subdirectory path is longer than PATH_MAX, Path.is_symlink() raises OSError ENAMETOOLONG. Python 3.13 pathlib re-raises that errno, and the call sits outside the contextlib.suppress block. The exception escapes _remove_run_dir and the finally block of run_python_code before shutil.rmtree runs, so the whole run dir and everything in it stays on disk. Trees shorter than PATH_MAX but deeper than the free fd budget are also left behind: Python 3.13 rmtree holds one fd per level, and ignore_errors hides the EMFILE. That case only logs 'Could not fully remove run directory', and the tool still reports success. Every call can leave data behind permanently, and repeated calls fill the server's working-directory filesystem. This applies in the shipped Docker mode (server root, code nonroot) and also in same-uid mode.

### Trace and evidence

1. **entrypoint** `src/mcp_run_isolated_python/mcp_server.py:28` `run_mcp tool registration` — code_executor.run_python_code is registered as the MCP tool, so python_code comes from any MCP caller (the HTTP transport has no auth). direct_use.py reaches the same method.
2. **propagation** `src/mcp_run_isolated_python/code_executor.py:251` `CodeExecutor.run_python_code` — The caller's code runs under srt with write access to its run dir. There it builds a directory tree 2100 levels deep with dir_fd-relative mkdir, which is never limited by PATH_MAX.
3. **propagation** `src/mcp_run_isolated_python/code_executor.py:267` `CodeExecutor.run_python_code finally` — _remove_run_dir(code_path) is called unguarded in the finally block
4. **propagation** `src/mcp_run_isolated_python/code_executor.py:66` `_remove_run_dir` — os.walk yields a root path longer than PATH_MAX. Path.is_symlink() -> lstat raises OSError ENAMETOOLONG (Python 3.13 pathlib does not ignore that errno), outside contextlib.suppress. The exception leaves the function and the finally block.
5. **sink** `src/mcp_run_isolated_python/code_executor.py:69` `_remove_run_dir` — shutil.rmtree is never reached in the deeper-than-PATH_MAX case. In the shorter-than-PATH_MAX case it fails on EMFILE, and ignore_errors hides that. Either way the run dir and its files stay on disk.

Evidence:
- `src/mcp_run_isolated_python/code_executor.py:64` — Path-based os.walk over a tree the sandbox controls
- `src/mcp_run_isolated_python/code_executor.py:66` — is_symlink() is outside the contextlib.suppress(OSError) block, which only wraps chmod at lines 67-68
- `src/mcp_run_isolated_python/code_executor.py:69` — shutil.rmtree(path, ignore_errors=True) with no fallback. Lines 70-71 only log an error.
- `src/mcp_run_isolated_python/code_executor.py:267` — The cleanup call in the finally block has no try/except, so a cleanup OSError escapes run_python_code and replaces the tool result
- `src/mcp_run_isolated_python/code_executor.py:243` — ulimit -f only caps the size of each file. Nothing limits total bytes, file count, or depth in the run dir.

### Principals
- Attacker: An MCP client, or a prompt-injected LLM, submitting Python code to run_python_code
- Invariant: The run directory and everything the sandbox wrote are always removed at the end of each run, whatever tree shape, depth or permission bits the sandbox created. A cleanup error must never skip the removal or replace the tool result.

### Reproduction

Payloads:
```python
import os
fd = os.open('.', os.O_RDONLY)
for i in range(2100):
    os.mkdir('d', dir_fd=fd); n = os.open('d', os.O_RDONLY, dir_fd=fd); os.close(fd); fd = n
f = os.open('leftover.bin', os.O_WRONLY|os.O_CREAT, 0o644, dir_fd=fd); os.write(f, b'x'*1000); os.close(f)
```

Steps:
1. In a Docker-equivalent environment (server as root, real srt+bwrap), build CodeExecutor(CodeSandboxSettings(user='nonroot', path_to_srt_settings=/code/default_srt_settings.json, path_to_python_interpreter=/sandbox/.venv/bin/python, working_directory=/work/wd, code_timeout_seconds=30)).
2. Control: call run_python_code with the payload at depth 300 and check that no new entry stays in /work/wd.
3. Call run_python_code with the depth-2100 payload twice, then once at depth 900. After each call, list the new entries in /work/wd, then run du -sb /work/wd.

### Observed result
Depth-300 control: status success, no entry left. Each depth-2100 call: the sandbox code finished with success, but run_python_code raised 'OSError [Errno 36] File name too long'. The traceback ran through code_executor.py:267 -> code_executor.py:66 (is_symlink -> lstat -> os.stat), and each call left its run dir behind. Depth-900 call: the tool returned success and the run dir was left behind. After the runs, 3 run dirs remained (du 3620 bytes with the 1000-byte payload files) (agents/ver-rmlock/artifacts/evidence1.txt). A direct call of the current _remove_run_dir on a depth-900 tree logged 'Could not fully remove run directory' and left the tree behind. An earlier fwalk/fchmod remediation left a locked (mode-0) tree behind even at depth 300 (agents/fin-rmlock/artifacts/evidence1.txt). The corrected remediation below was run under GNU coreutils 9.7 as uid 0 without DAC_OVERRIDE (CapEff 0, which matches same-uid mode). It removed trees at depths 300, 900 and 2100, with and without mode-0 directories, and a symlink target outside the tree kept mode 0500 (agents/fin-rmlock2/artifacts/evidence1.txt). The macOS BSD chmod/rm with the same argument order removed locked trees at depths 300 and 2100 without following symlinks. The earlier order `chmod -R -P u+rwx -- <path>` makes BSD chmod treat `--` as a file operand ('chmod: --: No such file or directory') (agents/fin-rmlock2/artifacts/evidence2.txt).

### Conditions and containment

- *authentication_level*: Any caller who can invoke run_python_code (the HTTP transport has no auth, which is an accepted finding carried over from run-1), or a prompt-injected LLM
- *system_configuration*: Reproduced in the Docker deployment shape: server as root, code as nonroot uid 999, real srt+bwrap, Python 3.13.15. The deeper-than-PATH_MAX variant does not depend on the fd limit or on file ownership, so it also applies in same-uid CLI/library mode. The EMFILE variant for trees shorter than PATH_MAX (depth 900 observed) depends on the server's RLIMIT_NOFILE (512 in the test).

### Remediation and regression case

Make cleanup independent of tree shape and never let it skip removal. Wrap the existing unlock walk and rmtree in try/except, and keep the is_symlink check inside the suppress block, so errors are logged and removal continues. If the path still exists afterwards, fall back to depth-safe fts-based tools that are available on both GNU and BSD/macOS: `chmod -R -P -- u+rwx <path>` (unlocks each directory at its preorder visit before it is entered, does not follow symlinks), then `rm -rf -- <path>`. Neither holds one fd per level or builds paths longer than PATH_MAX. Put `--` before the mode operand: BSD getopt stops at the first non-option, so a `--` placed after the mode becomes a stray file operand relative to the server's cwd. Do not switch the unlock to os.open()+fchmod: opening a mode-0 directory fails without DAC_OVERRIDE, which breaks the same-uid unlock that a80b830 added. os.fwalk also runs out of fds at about 500 levels. Avoid GNU-only flags. Because the guard sits inside _remove_run_dir, the finally block can no longer replace the tool result. As hardening, consider a total size/inode quota for the run dir. Add a regression test that creates a tree deeper than PATH_MAX, with a mode-0 directory at the bottom and a symlink to a directory outside the tree, and asserts the run dir is removed and the outside target is unchanged.

`src/mcp_run_isolated_python/code_executor.py`:
```
def _remove_run_dir(path: Path) -> None:
    try:
        # sandbox code owning its dirs (same-uid mode) can chmod them to block removal: unlock them first.
        with contextlib.suppress(OSError):
            path.chmod(stat.S_IRWXU)
        for root, dirs, _ in os.walk(path):
            for name in dirs:
                with contextlib.suppress(OSError):
                    if not (sub := Path(root) / name).is_symlink():
                        sub.chmod(stat.S_IRWXU)
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.exception("Run dir cleanup raised", path=str(path))
    if os.path.lexists(path):
        # the sandbox controls tree depth (> PATH_MAX, > fd limit): fts-based tools handle both, GNU and BSD alike.
        # '--' must precede the mode: BSD getopt stops at the first non-option.
        for cmd in (("chmod", "-R", "-P", "--", "u+rwx", str(path)), ("rm", "-rf", "--", str(path))):
            with contextlib.suppress(OSError):
                subprocess.run(cmd, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if os.path.lexists(path):
        logger.error("Could not fully remove run directory", path=str(path))
```

## Unauthenticated code-exec MCP endpoint accepts any Host/Origin (DNS rebinding to a localhost server; unauthenticated 0.0.0.0 exposure in Docker)

`mcp_server.py:run_mcp/http-transport-no-auth-no-host-origin-guard` — **medium**

run_mcp() starts the FastMCP streamable-HTTP transport with no authentication and no Host/Origin validation. In fastmcp 4.0.3 (pinned in uv.lock), settings.http_host_origin_protection defaults to False, so run_http_async does not install HostOriginGuardMiddleware. create_streamable_http_app also always passes TransportSecuritySettings(enable_dns_rebinding_protection=False) to the MCP SDK session manager. The project never overrides either setting and configures no auth provider. The server therefore executes a tools/call run_python_code request that carries an attacker hostname in both Host and Origin, and returns the output. CLI mode binds localhost, and the bind address is the only gate. A web page using DNS rebinding can therefore reach localhost:6400, run code through srt, and read the response. The default srt policy has denyRead []. The executor (current source a80b830) adds only the server working directory to denyRead, so the response can still include any other file the invoking user can read. Docker mode binds 0.0.0.0 (docker-entrypoint.sh), and compose publishes 6400:6400 on all host interfaces. Any network peer can therefore run code without credentials, and so can any web page via rebinding.

### Trace and evidence

1. **entrypoint** `src/mcp_run_isolated_python/cli.py:60` `run() mcp_host default` — The CLI binds 'localhost' by default. The HTTP endpoint at <host>:6400/mcp is the lower-trust entry and has no authentication. docker-entrypoint.sh:15 overrides this with --mcp_host=0.0.0.0, and docker-compose.yml:8 publishes 6400:6400.
2. **propagation** `src/mcp_run_isolated_python/mcp_server.py:49` `run_mcp` — mcp.run_async(...) is called with no host_origin_protection, allowed_hosts, allowed_origins or auth. fastmcp's default http_host_origin_protection=False applies, so HostOriginGuardMiddleware is not installed, and fastmcp disables the SDK DNS-rebinding check.
3. **propagation** `src/mcp_run_isolated_python/mcp_server.py:26` `run_mcp tool registration` — run_python_code is registered as a tool with no per-caller authorization.
4. **sink** `src/mcp_run_isolated_python/code_executor.py:139` `CodeExecutor._run_sandboxed (called from run_python_code, line 251)` — Caller code runs via subprocess.Popen(srt ...) as the configured user: the invoking user in CLI mode, nonroot in Docker. The per-run srt settings deny reads only of the server working directory on top of the base denyRead []. stdout/stderr and ./output files are returned to the HTTP caller (code_executor.py:254).

Evidence:
- `src/mcp_run_isolated_python/mcp_server.py:49` — run_async call without host/origin protection or auth arguments; FastMCP(name=name) at line 17 has no auth provider
- `src/mcp_run_isolated_python/cli.py:60` — Default bind 'localhost', the only network gate in CLI mode
- `docker-entrypoint.sh:15` — Docker mode binds 0.0.0.0
- `docker-compose.yml:8` — Port 6400 published on all host interfaces
- `default_srt_settings.json:9` — denyRead is empty, so sandboxed code can read any file its uid can read
- `src/mcp_run_isolated_python/code_executor.py:94` — The generated per-run policy adds only the server working directory to denyRead, so other user-readable files stay readable
- `uv.lock:409` — fastmcp pinned to 4.0.3, whose http_host_origin_protection defaults to False

### Principals
- Attacker: An unauthenticated HTTP client with no credentials. This is either a web page the local user visits, reaching localhost via DNS rebinding so the request carries the attacker's hostname in Host/Origin, or any network peer of a Docker deployment.
- Invariant: Only the intended local MCP client, or authenticated clients in a network deployment, can invoke run_python_code. A localhost-bound server rejects requests whose Host/Origin is not loopback or explicitly allowlisted, and a non-loopback bind requires authentication.

### Reproduction

Payloads:
```python
POST /mcp  Host: evil.rebind.example:6400  Origin: http://evil.rebind.example:6400  Content-Type: application/json  Accept: application/json, text/event-stream  body: {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"run_python_code","arguments":{"python_code":"import os;print(open('/scratch/dummy_v').read().strip(), os.getuid())"}}}
```

Steps:
1. Inside the no-network parent sandbox (sbx.py --srt, real srt+bwrap), start the real run_mcp(FullSettings(transport='http', stateless=True, host='localhost', port=6400, path='/mcp', user='nonroot', working_directory=/work/wd, path_to_srt_settings=/code/default_srt_settings.json, path_to_python_interpreter=/sandbox/.venv/bin/python)) from current source (a80b830, PYTHONPATH=/target/src). Create a dummy 0644 file /scratch/dummy_v containing VER-DUMMY-8842.
2. Send the payload to 127.0.0.1:<port> over container loopback with no auth header. Repeat with host='0.0.0.0' (the Docker entrypoint bind).
3. Control 1: repeat the localhost case with FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=true. Control 2: under the same strict protection, send Host/Origin localhost.

### Observed result
Re-reproduced on current source a80b830 with fastmcp 4.0.3 (installed default http_host_origin_protection=False). Localhost bind, foreign Host/Origin, no auth: HTTP 200, and the result output is 'VER-DUMMY-8842 999', so the code ran as uid 999 through srt plus the new unshare wrapper and returned the dummy file. 0.0.0.0 bind: HTTP 200 with the same output. Control 1 (strict protection, foreign Host): HTTP 421 Misdirected Request. Control 2 (strict protection, Host localhost): HTTP 200 with the same output, so the guard does not break legitimate loopback clients. Control 2 also shows that the Host guard alone does not stop a network peer on a 0.0.0.0 bind, because the peer can send Host: localhost, which is a DEFAULT_HOSTS entry (fastmcp/server/http.py:38). Evidence: agents/ver-httpauth/artifacts/evidence1.txt.

### Conditions and containment

- *user_interaction*: DNS-rebinding path (CLI/localhost mode): the user running the server visits an attacker-controlled page whose hostname re-resolves to 127.0.0.1, and the browser does not block the request (for example via Private Network Access). This browser step was not exercised locally.
- *system_configuration*: The operator has not set FASTMCP_HTTP_HOST_ORIGIN_PROTECTION or FASTMCP_HTTP_ALLOWED_HOSTS and runs the default http transport. For the direct network path, the server runs in the shipped Docker configuration (0.0.0.0 bind, port published) and the attacker's network can reach it.

### Remediation and regression case

Enforce two controls. (1) Always enable FastMCP's Host/Origin guard (host_origin_protection=True), with an operator-supplied allowed_hosts list for deployments reached under a non-loopback name. This closes DNS rebinding against loopback binds. (2) Require bearer-token authentication (FastMCP auth provider), and refuse to start the HTTP transport on a non-loopback bind when no token is configured. The Host guard alone does not protect 0.0.0.0 binds, because it always accepts Host: localhost/127.0.0.1/::1 and any network peer can send those. The Docker image and compose file must then provide MCP_AUTH_TOKEN, and clients send 'Authorization: Bearer <token>'. FullSettings has no allowed_hosts or auth_token fields today, so add both and read them from the environment, which leaves the CLI signature unchanged. In fastmcp 4.0.3, run_http_async accepts host_origin_protection and allowed_hosts, and fastmcp.server.auth.providers.jwt.StaticTokenVerifier exists.

`src/mcp_run_isolated_python/utils/settings.py`:
```
import os


def _env_list(name: str) -> list[str] | None:
    raw = os.environ.get(name, "").strip()
    return [h.strip() for h in raw.split(",") if h.strip()] or None


class FullSettings(CodeSandboxSettings):
    transport: str
    stateless: bool
    port: int
    host: str
    path: str
    log_level: int
    installed_python_dependencies: list[str] = Field(default_factory=list)
    # extra Host values accepted besides loopback (e.g. the Docker service name)
    allowed_hosts: list[str] | None = Field(default_factory=lambda: _env_list("MCP_ALLOWED_HOSTS"))
    # bearer token required from HTTP clients; mandatory for non-loopback binds
    auth_token: str | None = Field(default_factory=lambda: os.environ.get("MCP_AUTH_TOKEN") or None)
```

`src/mcp_run_isolated_python/mcp_server.py`:
```
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


async def run_mcp(settings: FullSettings):
    if settings.transport != "stdio" and settings.host not in _LOOPBACK_HOSTS and not settings.auth_token:
        raise SystemExit(
            f"Refusing to serve run_python_code on non-loopback host {settings.host!r} without authentication; set MCP_AUTH_TOKEN."
        )
    auth = (
        StaticTokenVerifier(tokens={settings.auth_token: {"client_id": "mcp-client", "scopes": []}})
        if settings.auth_token
        else None
    )
    mcp = FastMCP(name=name, auth=auth)
    ...
    await mcp.run_async(
        transport=settings.transport,  # ty:ignore[invalid-argument-type]
        stateless=settings.stateless,
        host=settings.host,
        port=settings.port,
        path=settings.path,
        show_banner=False,
        **(
            {"host_origin_protection": True, "allowed_hosts": settings.allowed_hosts}
            if settings.transport != "stdio"
            else {}
        ),
    )
```
