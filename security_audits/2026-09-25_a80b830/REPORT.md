# Security audit — mcp-run-isolated-python (run-3)

## 1. Scope and method

- **Profile:** `standard`. **Scope:** whole repository (`.`). **Budget:** none set. Agents spent: 11 hunters (9 in wave 1, 2 in wave 2), 3 coverage critics (post-wave 1, post-wave 2, distinct final-clean), 9 candidate verifiers and 10 Phase 5 final-record verifiers (one per record, plus one re-check of a remediation replacement). Reconnaissance was a parent-side delta over run-2 (changes limited to `code_executor.py`, `docker-compose.yml` and tests).
- **Source:** commit `a80b830`. The worktree is dirty only in `utils/logger.py` (import blank lines) and an untracked `.DS_Store`.
- **Execution:** sandboxed, source-and-local only. Target code ran only in a local Docker sandbox: `--network none`, read-only rootfs, cap-drop ALL, 512 MiB memory, 128 pids, 1 CPU, env allowlist, 120 s wall clock, scratch-only writes. `--srt` mode reproduced the project's Docker deployment with real srt 0.0.64 and bwrap. **No target code ran on the macOS host**, so the macOS/Seatbelt conclusions come from source review. No live endpoints were contacted.
- **Prior runs:** run-1 (`d099ead`) and run-2 (`5d3b260`) were read in full. Run-2's HTTP no-auth finding was carried (same source) and re-verified. Run-2's stdin-inheritance, SysV-IPC and srt-default-write-path findings are **closed** by a80b830 (revalidated). Run-2's resource-limits, output-aggregate, rmtree and macOS-descendant records were revalidated against the changed source; their current forms appear below. The run-2 rejected claim (Seatbelt POSIX IPC/notifications) stays suppressed because its evidence is unchanged.
- **Deferred / out of scope:** nothing deferred. Not exercised: Windows and non-Docker Linux hosts, deployed instances, and the macOS runtime.

## 2. Posture summary

a80b830 closed all three run-2 cross-run isolation findings. What remains: (1) the HTTP transport is still unauthenticated and does no Host/Origin check, so any network peer or rebinding web page reaches everything below; (2) the new resource controls don't add up, because per-run caps (256 processes) are not sized against the container pool (512) and nothing limits concurrency; (3) the new `_remove_run_dir` unlock walk is defeated by deep trees, and on macOS its path-based chmod is a TOCTOU lead; (4) several low-impact leftovers and log-hygiene gaps. No finding lets sandboxed code break out of bwrap in the shipped Docker deployment.

## 3. Confirmed findings

| # | Severity | Title | Boundary | Observed |
|---|---|---|---|---|
| 1 | **medium** | Per-run process caps are not sized against the shared container pid pool and there is no limit on concurrent runs, so two unauthenticated requests make other clients' runs fail (and runs still have no memory bound) | one client's runs → server and concurrent runs (availability) | Each run gets its own 256-process cap (the unshare user namespace makes RLIMIT_NPROC per run), but the container pids_limit is 512. Two runs exhaust the pid pool, and concurrent runs and the server's Popen fail with EAGAIN. There is no memory bound per run. |
| 2 | **medium** | Sandboxed code can make its run directory survive cleanup by creating a very deep directory tree (the a80b830 unlock-then-rmtree fix is incomplete) | sandboxed run → persistence past cleanup | A 2100-level directory tree makes the unlock walk fail with ENAMETOOLONG at :66, and a 900-level tree hits EMFILE. In both cases the run directory survives cleanup. |
| 3 | **medium** | Unauthenticated code-exec MCP endpoint accepts any Host/Origin (DNS rebinding to a localhost server; unauthenticated 0.0.0.0 exposure in Docker) | network client / browser origin → code-execution tool | Re-reproduced on a80b830. A foreign Host/Origin with no credentials got HTTP 200 and executed code. |
| 4 | **low** | Output-file aggregate bound counts only data bytes: many zero-byte files bypass it and collection runs unbounded past the code timeout | sandboxed run → server time past the timeout | 9,598 zero-byte files pass the byte budget, and collecting them took 9.82 s after the code timeout had expired. |
| 5 | **low** | Sandboxed code and MCP callers can inject raw terminal escape sequences into the operator's server log stream | sandboxed run / MCP caller → operator terminal (log injection) | An output filename containing ESC sequences was written raw to the structlog console output. |
| 6 | **low** | Every run leaves srt temp dirs and sockets in shared /tmp because TMPDIR is not set (CLAUDE_CODE_TMPDIR does not cover them) | run → shared host /tmp (leftovers) | Each run leaves 3–4 srt entries (dirs and sockets) in /tmp, because CLAUDE_CODE_TMPDIR does not cover them and TMPDIR is unset. |
| 7 | **low** | No concurrent-run admission control: 40 concurrent long runs from one unauthenticated client fill FastMCP's shared 40-thread pool and delay every other client's tool calls | one client → other clients' tool calls (queueing) | 40 long runs filled the 40-thread anyio pool. A victim's call took 14.62 s instead of 8.02 s. |

### 1. Per-run process caps are not sized against the shared container pid pool and there is no limit on concurrent runs, so two unauthenticated requests make other clients' runs fail (and runs still have no memory bound)

`code_executor.py:_run_sandboxed/no-per-run-resource-limits` — **medium** (likelihood high, impact medium; confidence high)

- **Location:** `src/mcp_run_isolated_python/code_executor.py:160` (CodeExecutor._run_sandboxed)
- **Lower-trust principal:** An unauthenticated MCP client submits two concurrent fork-loop runs that exhaust the shared container pid pool. A different client's ordinary run submitted during that window fails. Reproduced through the library API in the project's Docker image under real srt 0.0.64 + bwrap, with the server as root and code as uid 999.
- **Root cause:** The only per-run limits are the shell ulimits in run_python_code (code_executor.py:242-243, MAX_SANDBOX_PROCESSES=256 at :36). _run_sandboxed (code_executor.py:139-150) starts each run with Popen and has no memory limit or per-run cgroup. run_python_code has no admission control: no semaphore, no concurrency cap, no per-caller limit. The per-run caps therefore add up with no bound against the one container pid pool (docker-compose.yml pids_limit 512; none in the README `docker run`). The server's own fork for new runs draws from that same pool, and memory has no per-run bound at all.

**Reproduction (bounded, local):**

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

**Conditions:**
- *authentication_level*: No authentication: any client that can reach the MCP HTTP endpoint (Docker publishes 0.0.0.0:6400), or a prompt-injected LLM, can submit runs.
- *timing_dependency*: The victim's request must arrive while the attacker runs are active (up to code_timeout_seconds, 30s by default). The attacker resubmits to keep the window open.
- *system_configuration*: The number of attacker requests needed depends on the container pid limit. The shipped compose (pids_limit 512 against a 256-per-run cap) needs two concurrent runs. Any limit at or below 256 needs one. The README docker run sets no pids limit, so exhaustion there depends on host limits (not exercised). The memory impact depends on whether a container memory limit is set.
- *environmental_dependency*: Per-run NPROC accounting depends on Linux with the unshare wrapper and ucounts (kernel 5.14 or later; verified on 6.8). macOS CLI mode has no user namespace, so the cap counts per host uid there (not verified).

**Observed result:** Per-run check (agents/ver-limits/artifacts/evidence1.txt): the attacker stopped at 27 forks with EAGAIN from its own cap of 30. The concurrent victim ran as uid 999 with Max processes 30 and forked all 10 children. So the cap is per run, not a per-uid pool. Starvation check (agents/ver-limits/artifacts/evidence2.txt): attacker 1 hit its own cap at 57 forks. Attacker 2 got 21 forks before EAGAIN from the container pid cgroup. The victim run returned status='failure', 'Tool run failed. Do not call this tool again, inform the user that it is broken.', with BlockingIOError [Errno 11] raised in the server's own subprocess.Popen. The run after the attack returned status='success', 'recovered'. The hunter's single-run result (102 forks, victim failed) came from the fixture's 128-pid cgroup being below the 256 cap.

**Impact:** Availability only. Concurrent clients' runs fail and they are told the tool is broken for up to code_timeout_seconds per attack round. The root server process stays up and recovers automatically. Memory exhaustion without a container memory limit was not exercised.

**Priority rationale:** Unauthenticated and trivial: two concurrent fork-loop requests under the shipped compose limits (one where the container pid limit is 256 or less), repeatable at will.

**Smallest fix:** Bound the total, not only each run. (1) Add admission control in run_python_code: a process-wide BoundedSemaphore of MAX_CONCURRENT_RUNS, acquired without blocking; when full, return a 'busy, retry later' result instead of the 'tool is broken' message. (2) Size MAX_SANDBOX_PROCESSES so that MAX_CONCURRENT_RUNS × cap + srt/node/bwrap threads + server headroom stays below the container pids_limit. For example, 4 runs × 64 against 512. Keep the cap before `unshare --user` so it stays per run on Linux. (3) Add a per-run memory cap for the interpreter only (`ulimit -v`, not on srt/node), sized so that the concurrent runs together fit under mem_limit. (4) Document --pids-limit and --memory in the README `docker run` command. (5) Better long-term fix: a per-run cgroup (pids.max/memory.max) so the server's own forks never share a budget with sandboxed code. Regression test: with MAX_CONCURRENT_RUNS fork-loop runs active, one more run returns busy and does not raise in Popen, and a run submitted after they end succeeds.

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

### 2. Sandboxed code can make its run directory survive cleanup by creating a very deep directory tree (the a80b830 unlock-then-rmtree fix is incomplete)

`code_executor.run_python_code:rmtree-ignore-errors-sandbox-locked-dir` — **medium** (likelihood high, impact medium; confidence high)

- **Location:** `src/mcp_run_isolated_python/code_executor.py:69` (_remove_run_dir)
- **Lower-trust principal:** An MCP client, or a prompt-injected LLM, submitting Python code to run_python_code
- **Root cause:** The cleanup code assumes a tree shape that is safe for path-based walking and for recursion that holds one fd per level, but the sandbox controls that shape completely. code_executor.py:66 calls (Path(root) / name).is_symlink() without catching OSError, so ENAMETOOLONG propagates out of _remove_run_dir before shutil.rmtree at line 69 runs. shutil.rmtree(ignore_errors=True) at line 69 silently gives up on EMFILE. There is no fallback removal and no guard around the cleanup as a whole. Lines 70-71 only log.

**Reproduction (bounded, local):**

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

**Conditions:**
- *authentication_level*: Any caller who can invoke run_python_code (the HTTP transport has no auth, which is an accepted finding carried over from run-1), or a prompt-injected LLM
- *system_configuration*: Reproduced in the Docker deployment shape: server as root, code as nonroot uid 999, real srt+bwrap, Python 3.13.15. The deeper-than-PATH_MAX variant does not depend on the fd limit or on file ownership, so it also applies in same-uid CLI/library mode. The EMFILE variant for trees shorter than PATH_MAX (depth 900 observed) depends on the server's RLIMIT_NOFILE (512 in the test).

**Observed result:** Depth-300 control: status success, no entry left. Each depth-2100 call: the sandbox code finished with success, but run_python_code raised 'OSError [Errno 36] File name too long'. The traceback ran through code_executor.py:267 -> code_executor.py:66 (is_symlink -> lstat -> os.stat), and each call left its run dir behind. Depth-900 call: the tool returned success and the run dir was left behind. After the runs, 3 run dirs remained (du 3620 bytes with the 1000-byte payload files) (agents/ver-rmlock/artifacts/evidence1.txt). A direct call of the current _remove_run_dir on a depth-900 tree logged 'Could not fully remove run directory' and left the tree behind. An earlier fwalk/fchmod remediation left a locked (mode-0) tree behind even at depth 300 (agents/fin-rmlock/artifacts/evidence1.txt). The corrected remediation below was run under GNU coreutils 9.7 as uid 0 without DAC_OVERRIDE (CapEff 0, which matches same-uid mode). It removed trees at depths 300, 900 and 2100, with and without mode-0 directories, and a symlink target outside the tree kept mode 0500 (agents/fin-rmlock2/artifacts/evidence1.txt). The macOS BSD chmod/rm with the same argument order removed locked trees at depths 300 and 2100 without following symlinks. The earlier order `chmod -R -P u+rwx -- <path>` makes BSD chmod treat `--` as a file operand ('chmod: --: No such file or directory') (agents/fin-rmlock2/artifacts/evidence2.txt).

**Impact:** Files the sandbox writes (each up to about 100 MB, with no limit on count) stay on the server's filesystem after the run. They pile up across requests, and nothing removes them automatically, so a shared service can run out of disk. The deep case also turns the tool result into an exception. denyRead keeps the leftovers hidden from other runs, so nothing is disclosed.

**Priority rationale:** One small, deterministic payload from any caller of the tool, which has no auth over HTTP. Works in the shipped Docker mode and in same-uid mode.

**Smallest fix:** Make cleanup independent of tree shape and never let it skip removal. Wrap the existing unlock walk and rmtree in try/except, and keep the is_symlink check inside the suppress block, so errors are logged and removal continues. If the path still exists afterwards, fall back to depth-safe fts-based tools that are available on both GNU and BSD/macOS: `chmod -R -P -- u+rwx <path>` (unlocks each directory at its preorder visit before it is entered, does not follow symlinks), then `rm -rf -- <path>`. Neither holds one fd per level or builds paths longer than PATH_MAX. Put `--` before the mode operand: BSD getopt stops at the first non-option, so a `--` placed after the mode becomes a stray file operand relative to the server's cwd. Do not switch the unlock to os.open()+fchmod: opening a mode-0 directory fails without DAC_OVERRIDE, which breaks the same-uid unlock that a80b830 added. os.fwalk also runs out of fds at about 500 levels. Avoid GNU-only flags. Because the guard sits inside _remove_run_dir, the finally block can no longer replace the tool result. As hardening, consider a total size/inode quota for the run dir. Add a regression test that creates a tree deeper than PATH_MAX, with a mode-0 directory at the bottom and a symlink to a directory outside the tree, and asserts the run dir is removed and the outside target is unchanged.

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

### 3. Unauthenticated code-exec MCP endpoint accepts any Host/Origin (DNS rebinding to a localhost server; unauthenticated 0.0.0.0 exposure in Docker)

`mcp_server.py:run_mcp/http-transport-no-auth-no-host-origin-guard` — **medium** (likelihood medium, impact high; confidence high)

- **Location:** `src/mcp_run_isolated_python/code_executor.py:139` (CodeExecutor._run_sandboxed (called from run_python_code, line 251))
- **Lower-trust principal:** An unauthenticated HTTP client with no credentials. This is either a web page the local user visits, reaching localhost via DNS rebinding so the request carries the attacker's hostname in Host/Origin, or any network peer of a Docker deployment.
- **Root cause:** mcp_server.py:49-56 calls mcp.run_async(transport, stateless, host, port, path, show_banner) without host_origin_protection, allowed_hosts or allowed_origins, and without an auth provider (FastMCP(name=name) at mcp_server.py:17). fastmcp 4.0.3 then falls back to http_host_origin_protection=False (fastmcp/settings.py:280). That skips HostOriginGuardMiddleware (fastmcp/server/http.py:656), and fastmcp explicitly disables the SDK's DNS-rebinding check (http.py:675-680). The endpoint has no Host/Origin guard and no authentication, so the bind address is the only control. DNS rebinding bypasses a localhost bind, and the Docker 0.0.0.0 bind removes that control entirely.

**Reproduction (bounded, local):**

Payloads:
```python
POST /mcp  Host: evil.rebind.example:6400  Origin: http://evil.rebind.example:6400  Content-Type: application/json  Accept: application/json, text/event-stream  body: {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"run_python_code","arguments":{"python_code":"import os;print(open('/scratch/dummy_v').read().strip(), os.getuid())"}}}
```

Steps:
1. Inside the no-network parent sandbox (sbx.py --srt, real srt+bwrap), start the real run_mcp(FullSettings(transport='http', stateless=True, host='localhost', port=6400, path='/mcp', user='nonroot', working_directory=/work/wd, path_to_srt_settings=/code/default_srt_settings.json, path_to_python_interpreter=/sandbox/.venv/bin/python)) from current source (a80b830, PYTHONPATH=/target/src). Create a dummy 0644 file /scratch/dummy_v containing VER-DUMMY-8842.
2. Send the payload to 127.0.0.1:<port> over container loopback with no auth header. Repeat with host='0.0.0.0' (the Docker entrypoint bind).
3. Control 1: repeat the localhost case with FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=true. Control 2: under the same strict protection, send Host/Origin localhost.

**Conditions:**
- *user_interaction*: DNS-rebinding path (CLI/localhost mode): the user running the server visits an attacker-controlled page whose hostname re-resolves to 127.0.0.1, and the browser does not block the request (for example via Private Network Access). This browser step was not exercised locally.
- *system_configuration*: The operator has not set FASTMCP_HTTP_HOST_ORIGIN_PROTECTION or FASTMCP_HTTP_ALLOWED_HOSTS and runs the default http transport. For the direct network path, the server runs in the shipped Docker configuration (0.0.0.0 bind, port published) and the attacker's network can reach it.

**Observed result:** Re-reproduced on current source a80b830 with fastmcp 4.0.3 (installed default http_host_origin_protection=False). Localhost bind, foreign Host/Origin, no auth: HTTP 200, and the result output is 'VER-DUMMY-8842 999', so the code ran as uid 999 through srt plus the new unshare wrapper and returned the dummy file. 0.0.0.0 bind: HTTP 200 with the same output. Control 1 (strict protection, foreign Host): HTTP 421 Misdirected Request. Control 2 (strict protection, Host localhost): HTTP 200 with the same output, so the guard does not break legitimate loopback clients. Control 2 also shows that the Host guard alone does not stop a network peer on a 0.0.0.0 bind, because the peer can send Host: localhost, which is a DEFAULT_HOSTS entry (fastmcp/server/http.py:38). Evidence: agents/ver-httpauth/artifacts/evidence1.txt.

**Impact:** Anyone who reaches the endpoint can run code without authentication and receives the output. In CLI mode, code runs as the invoking user under srt, and only the server working directory is denied, so user-readable files can be disclosed to a remote web origin. In Docker, an attacker gets arbitrary sandboxed execution as nonroot and can read container files.

**Priority rationale:** In CLI mode the victim must visit an attacker page and DNS rebinding must succeed, and browser mitigations vary. Network peers can reach the shipped Docker configuration directly without credentials.

**Smallest fix:** Enforce two controls. (1) Always enable FastMCP's Host/Origin guard (host_origin_protection=True), with an operator-supplied allowed_hosts list for deployments reached under a non-loopback name. This closes DNS rebinding against loopback binds. (2) Require bearer-token authentication (FastMCP auth provider), and refuse to start the HTTP transport on a non-loopback bind when no token is configured. The Host guard alone does not protect 0.0.0.0 binds, because it always accepts Host: localhost/127.0.0.1/::1 and any network peer can send those. The Docker image and compose file must then provide MCP_AUTH_TOKEN, and clients send 'Authorization: Bearer <token>'. FullSettings has no allowed_hosts or auth_token fields today, so add both and read them from the environment, which leaves the CLI signature unchanged. In fastmcp 4.0.3, run_http_async accepts host_origin_protection and allowed_hosts, and fastmcp.server.auth.providers.jwt.StaticTokenVerifier exists.

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

### 4. Output-file aggregate bound counts only data bytes: many zero-byte files bypass it and collection runs unbounded past the code timeout

`code_executor._collect_output_files:no-aggregate-output-file-bound` — **low** (likelihood high, impact low; confidence high)

- **Location:** `src/mcp_run_isolated_python/code_executor.py:219` (CodeExecutor._collect_output_files)
- **Lower-trust principal:** MCP client that submits Python code to run_python_code (Docker deployment: server as root, code as nonroot inside real srt+bwrap).
- **Root cause:** code_executor.py:201-204 enforce the aggregate limit only on len(data), so zero-byte entries always pass and never consume budget; line 188 enumerates every entry of the sandbox-writable output dir with no entry-count limit; and line 254 calls _collect_output_files after proc.wait() (line 160) with no time bound. Entry count, filename length, and per-item object/JSON overhead are never charged against any bound.

**Reproduction (bounded, local):**

Payloads:
```python
i=0
while True:
    open(f'output/{i:0200d}.txt','wb').close(); i+=1
```

Steps:
1. Inside sbx.py --srt (real srt + bubblewrap, server root, code nonroot, /code/default_srt_settings.json, working_directory=/scratch/wd), construct CodeExecutor with code_timeout_seconds and call run_python_code with the payload (files created until the code timeout kills the sandbox).
2. Wrap _collect_output_files to measure its wall time, the number of returned items, the summed model_dump_json length, and /proc/self/statm RSS growth; also record the total tool-call wall time vs the code timeout.

**Conditions:**
- *authentication_level*: Anyone who can call the run_python_code tool (unauthenticated HTTP transport, carried finding) or steer the LLM into running code.
- *environmental_dependency*: How many entries can be created depends on the run-dir filesystem's file-creation speed within code_timeout_seconds (default 30 s); post-timeout collection time and returned item count scale linearly and add up across concurrent requests.

**Observed result:** Independently reproduced (agents/ver-outagg/artifacts/evidence1.txt). code_timeout_seconds=8: 9,598 zero-byte files created; _collect_output_files then ran 9.82 s AFTER the code timeout (tool call wall 21.4 s vs 8 s advertised timeout); 9,598 content items returned; 3,176,938 JSON bytes; server RSS grew 14,426,112 bytes; 0 bytes charged to the 200 MB budget; run dir removed afterwards. Consistent with h-output evidence1 on a faster filesystem: 40,940 files, 21.14 s post-timeout collection, 40,941 items, 13,551,140 JSON bytes, +55,717,888 RSS, 0 bytes charged. Server takedown was not attempted; the residual is a shared worker held well past the timeout plus tens of MB per request, scaling with fs speed and concurrency.

**Impact:** Observed impact is a shared server worker held ~10-21 s past the code timeout plus tens of MB of server memory and a few-to-13 MB JSON response per request; full process takedown was not demonstrated and depends on filesystem speed and concurrency.

**Priority rationale:** A single unauthenticated tool call with a trivial payload; no special conditions, and reachable directly over the no-auth HTTP transport or via a prompt-injected LLM.

**Smallest fix:** Charge every entry against a bound: cap the number of returned entries, count a per-entry overhead plus the name length toward the aggregate budget, and stop scanning as soon as a cap is hit (do not read the whole directory). Also check st_size from fstat before reading so files that would go over budget are not read at all.

`src/mcp_run_isolated_python/code_executor.py`:
```
MAX_OUTPUT_FILES = 100
...
            for count, name in enumerate(os.listdir(dir_fd)):
                if count >= MAX_OUTPUT_FILES:
                    logger.warning("Too many output files, skipping the rest")
                    break
                ...
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_OUTPUT_FILE_BYTES or total + st.st_size + len(name) > MAX_TOTAL_OUTPUT_FILE_BYTES:
                    os.close(fd)
                    continue
                ...
                total += len(data) + len(name)
```

### 5. Sandboxed code and MCP callers can inject raw terminal escape sequences into the operator's server log stream

`code_executor._collect_output_files:sandbox-controlled-output-name-logged-raw-terminal-escape-injection` — **low** (likelihood low, impact low; confidence high)

- **Location:** `src/mcp_run_isolated_python/utils/logger.py:24` (configure_logging)
- **Lower-trust principal:** Code executed inside the srt/bwrap sandbox as uid 999 with Docker-mode settings, whose only capability is writing its own ./output directory. Alternatively, an MCP client supplying the python_code argument
- **Root cause:** The shared renderer prints untrusted str field values without escaping them. structlog.dev.ConsoleRenderer is built without repr_native_str=True (utils/logger.py:24), and code_executor.py passes names chosen by the sandbox (lines 192, 197, 202) and the tool argument (line 240) as native str fields. structlog escapes only whitespace, '=' and quote characters, not other control bytes.

**Reproduction (bounded, local):**

Payloads:
```python
import os
os.mkdir('output/'+'\x1b[1A\x1b[2KVERLOGESC\x1b]0;VTITLE\x07')
os.symlink('/etc/passwd','output/'+'\x1bcSYM')

```
```python
#\x1b]0;CODETITLE\x07
```

Steps:
1. In the parent sandbox launcher in --srt mode (real srt + bubblewrap, server as container root, code as nonroot), construct CodeSandbox(settings=CodeSandboxSettings(user='nonroot', path_to_srt_settings='/code/default_srt_settings.json', path_to_python_interpreter='/sandbox/.venv/bin/python', working_directory='/scratch/wdv', code_timeout_seconds=20)) and enter it as a context manager
2. Call eval() with the first payload, then with the second payload (a code string containing raw ESC/BEL and no whitespace or quotes), with the server process's stdout redirected to a file
3. Inspect the 'Skipping output entry ...' and 'Running python code...' lines with od -c

**Conditions:**
- *user_interaction*: An operator views the server's stdout (the foreground CLI, a foreground `docker run`, or `docker logs`/compose logs, or a library caller's stdout) in a terminal emulator that interprets the injected sequences
- *authentication_level*: The attacker only needs code to run through run_python_code: an unauthenticated MCP HTTP client or a prompt-injected LLM. For the code= path, the attacker only needs to send the tool argument
- *third_party_dependency*: The impact depends on the terminal. Reset, cursor/erase and title sequences work in nearly all terminals. OSC 52 clipboard writes work only where the terminal allows them (not tested)

**Observed result:** Three values appeared on server stdout as raw, unescaped control bytes. name= showed 033 c (RIS terminal reset) for the symlink. name= showed 033 [ 1 A 033 [ 2 K VERLOGESC 033 ] 0 ; VTITLE \a for the directory. code= showed # 033 ] 0 ; CODETITLE \a. The first code string, which contains spaces and newlines, was repr-quoted. Evidence: agents/ver-logesc/artifacts/evidence1.txt. The impact on a live terminal was not tested; only the raw bytes on the log stream were observed.

**Impact:** Integrity of the operator's terminal and logs: reset, hiding or spoofing earlier lines, and title changes. Clipboard writes are possible only on permissive terminals. No code execution or data disclosure.

**Priority rationale:** Any caller or sandboxed code can trigger it trivially, but it has an effect only when a human views the logs in a terminal that interprets the sequences

**Smallest fix:** Set repr_native_str=True in the shared ConsoleRenderer. This one change escapes every native str field value (name=, code=, cmd= and any others) for all callers. As defence in depth, log repr(name) for names chosen by the sandbox.

`src/mcp_run_isolated_python/utils/logger.py`:
```
            structlog.dev.ConsoleRenderer(pad_event_to=60, exception_formatter=exception_formatter, repr_native_str=True),
```

### 6. Every run leaves srt temp dirs and sockets in shared /tmp because TMPDIR is not set (CLAUDE_CODE_TMPDIR does not cover them)

`code_executor._run_sandboxed:srt-host-tmp-artifacts-leak-per-run` — **low** (likelihood medium, impact low; confidence high)

- **Location:** `src/mcp_run_isolated_python/code_executor.py:147` (CodeExecutor._run_sandboxed)
- **Lower-trust principal:** An MCP client calling run_python_code repeatedly with trivial code
- **Root cause:** The Popen env at code_executor.py:147 redirects only CLAUDE_CODE_TMPDIR, not TMPDIR. srt's os.tmpdir()-based artifacts (linux-sandbox-utils.js:367,370,714; mux-proxy.js:22 in srt 0.0.64) are therefore created in /tmp, outside the per-run directory that the finally block removes.

**Reproduction (bounded, local):**

Payloads:
```python
print(1)
```
```python
import time; time.sleep(60)
```

Steps:
1. In the --srt parent sandbox (real srt 0.0.64 and bwrap, Docker-mode settings), build CodeExecutor(user='nonroot', code_timeout_seconds=3, path_to_srt_settings=/code/default_srt_settings.json, working_directory=/work/wd). Snapshot os.listdir('/tmp'), run 'print(1)' twice, and diff the listing
2. Snapshot again, run the sleep payload once (it times out and is SIGKILLed), and diff
3. Confirm that the working directory holds no leftover run dirs
4. Fix check: wrap subprocess.Popen to add only TMPDIR=<run dir> to the env, repeat 2 normal runs and 1 timed-out run, and diff /tmp

**Conditions:**
- *authentication_level*: Any MCP client able to call run_python_code. The HTTP transport has no authentication (the owner accepts this as operator responsibility)
- *third_party_dependency*: srt (sandbox-runtime) <=0.0.64 on Linux, which puts claude-empty-*, claude-http-*.sock and srt-mux-*.sock under os.tmpdir() (verified in the image, version 0.0.64)
- *environmental_dependency*: Meaningful impact needs many calls. Growth is about 3-4 inodes (about 2 directory blocks) per call in the /tmp filesystem shared by the server, which is the container writable layer in Docker mode and the host /tmp in CLI mode

**Observed result:** Two normal runs left 7 new /tmp entries: 4 claude-empty-* dirs (mode 0700), 1 claude-http-*.sock and 2 srt-mux-*.sock. One timed-out run left 4 more: 2 claude-empty-*, 1 claude-http-*.sock and 1 srt-mux-*.sock. The working directory was empty afterwards. Sandboxed code could list these names in /tmp but got OSError when it tried to write there. With TMPDIR set to the run dir, the same 3 runs added 0 /tmp entries and no run dirs were left (agents/ver-srttmp/artifacts/evidence1.txt, evidence2.txt).

**Impact:** Only empty 0700 dirs and stale socket inodes (about 3-4 per call) build up in the shared /tmp. They slowly consume inodes and directory blocks until someone cleans up manually or recreates the container or tmp. No content is exposed and nothing is writable by other runs

**Priority rationale:** The leak happens on every tool call with no special payload and needs no authentication. A noticeable effect takes a large number of calls, though, and each call costs at least one sandbox start

**Smallest fix:** Give srt a per-run TMPDIR that cleanup removes. Preferably use a separate per-run tempfile.mkdtemp directory outside working_directory, chowned to settings.user, passed as both TMPDIR and CLAUDE_CODE_TMPDIR, and removed in run_python_code's finally block alongside the run dir. This keeps srt's mask dirs and proxy sockets out of the sandbox-writable cwd. Keep the path short so socket paths stay under the 108-byte AF_UNIX limit. Apply the same env to the model_post_init pre-check, which also runs srt.

`src/mcp_run_isolated_python/code_executor.py`:
```
env={"PATH": os.environ.get("PATH", ""), "CLAUDE_CODE_TMPDIR": str(srt_tmp), "TMPDIR": str(srt_tmp)},  # srt_tmp: per-run mkdtemp outside working_directory, chowned to settings.user, removed in run_python_code's finally
```

### 7. No concurrent-run admission control: 40 concurrent long runs from one unauthenticated client fill FastMCP's shared 40-thread pool and delay every other client's tool calls

`code_executor.py:run_python_code/no-concurrent-run-admission-shared-anyio-threadpool` — **low** (likelihood medium, impact low; confidence high)

- **Location:** `src/mcp_run_isolated_python/code_executor.py:160` (CodeExecutor._run_sandboxed)
- **Lower-trust principal:** Unauthenticated MCP HTTP client sharing the server with other clients.
- **Root cause:** The only limit on concurrent code runs is the framework's implicit default: anyio's process-wide 40-token thread limiter, shared with every other sync tool call. The application never adds its own admission control, per-caller or per-client concurrency quota, or fast busy rejection. Each admitted run keeps its slot for up to code_timeout_seconds (code_executor.py:160, 224; mcp_server.py:26-42, 49-56).

**Reproduction (bounded, local):**

Payloads:
```python
tools/call run_python_code {"python_code": "import time; time.sleep(10**6)"} sent 40 times concurrently
```

Steps:
1. Open 40 concurrent MCP sessions to http://<host>:6400/mcp and in each call run_python_code with a payload that sleeps past code_timeout_seconds.
2. About 1.5 s later, as a separate client, call run_python_code with print(1).
3. Measure the victim's latency against a baseline of 39 attacker calls.

**Conditions:**
- *authentication_level*: Attacker can reach the MCP HTTP endpoint. There is no authentication (exposure accepted by the owner as the operator's responsibility).
- *system_configuration*: CLI deployment or the README `docker run` without a pids limit. Under docker-compose pids_limit 512, runs fail at about 24 concurrent (a different effect, covered by the process-ceiling finding) before the 40-thread pool fills.
- *timing_dependency*: The victim's call must arrive while all 40 slots are held. The delay per wave is at most code_timeout_seconds, and the attacker has to keep sending waves to keep it going.
- *third_party_dependency*: The limit comes from anyio's default CapacityLimiter(40) as used by FastMCP 4.0.3 call_sync_fn_in_threadpool.

**Observed result:** Local test (agents/ver-admission/artifacts/evidence1.txt): real run_mcp/FastMCP HTTP server and real run_python_code, with only the sandbox subprocess replaced by an 8 s sleep. The server's default thread limiter had total_tokens=40. With 39 attackers the victim took 8.02 s, its own run only. With 40 attackers it took 14.62 s, about 6.6 s of that queued behind attacker slots. With real srt+bwrap (Docker-equivalent, uid 999), one sleeping run completed successfully with a peak of 21 uid-999 tasks (evidence2.txt). 40 real concurrent srt runs were not launched because of the local sandbox pids limit of 128.

**Impact:** Availability only. Other clients' tool calls are delayed up to code_timeout_seconds per wave, and the attacker has to keep sending for the delay to last. No data exposure, no crash, and recovery is automatic and immediate once the attacker stops.

**Priority rationale:** Unauthenticated, cheap (40 small requests per timeout window) and needs no process exhaustion. It is the binding limit in CLI and plain `docker run` deployments. Under docker-compose, pids_limit binds first.

**Smallest fix:** Put explicit admission control in front of execution: cap concurrent runs per client (per authenticated principal if auth is added in front, otherwise per client IP as a stopgap), keep the global cap below the thread pool size so capacity is left for others, and return an immediate busy result instead of silently queueing. Keep code_timeout_seconds low, and deploy behind authentication with per-principal quotas. That is the only real per-caller fairness, since the server has no identity of its own.

`src/mcp_run_isolated_python/code_executor.py`:
```
import collections
from fastmcp.server.dependencies import get_http_request

MAX_CONCURRENT_RUNS = 16  # below anyio's 40-thread default
MAX_RUNS_PER_CLIENT = 2
_global_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
_per_client: collections.Counter[str] = collections.Counter()
_per_client_lock = threading.Lock()


def _client_key() -> str:
    try:
        req = get_http_request()
        return req.client.host if req.client else "unknown"
    except RuntimeError:  # library use, no HTTP request
        return "local"

# in CodeExecutor.run_python_code, before _make_run_dir:
        key = _client_key()
        with _per_client_lock:
            if _per_client[key] >= MAX_RUNS_PER_CLIENT:
                return [CodeExecutionResult(status="failure", output="Too many concurrent runs for this client, retry later.")]
            _per_client[key] += 1
        if not _global_slots.acquire(blocking=False):
            with _per_client_lock:
                _per_client[key] -= 1
            return [CodeExecutionResult(status="failure", output="Server busy, retry later.")]
        try:
            ...  # existing body
        finally:
            _global_slots.release()
            with _per_client_lock:
                _per_client[key] -= 1

```

## 4. NEEDS VALIDATION (not confirmed, no severity)

| Title | Trace | Blocker | Local next step | Owner check |
|---|---|---|---|---|
| TOCTOU in _remove_run_dir: a surviving sandbox descendant can make the unsandboxed server chmod any same-uid file or directory outside the run dir to 0700 (macOS CLI/library mode) | `code_executor.py:251` → `code_executor.py:160` → `code_executor.py:267` → `code_executor.py:66` → `code_executor.py:68` | macOS Seatbelt cannot run in the Linux parent sandbox, and running target code on the host macOS is prohibited. The end-to-end chain on the only affected platform cannot be observed here. Decisive fact 1 (owned by u14): on macOS with srt's Seatbelt backend and user=None, a setsid/double-forked descendant of the sandboxed interpreter keeps running after a normal (non-timeout) run exit and is still running while _remove_run_dir executes. This was refuted for Linux/Docker (evidence2) but is unverified on macOS. Decisive fact 2: srt's macOS Seatbelt profile lets that descendant rmdir/rename a subdirectory of its cwd and create a symlink there whose target is outside the allowWrite scope. Symlink creation is expected to be checked against the link path, not the target, but this is not verified. | On a macOS host with srt <=0.0.64 installed, create a scratch dir S containing S/work and a dummy S/dummy_target set to mode 0o555. Instantiate CodeSandbox/CodeExecutor with CodeSandboxSettings(user=None, code_timeout_seconds=10, path_to_srt_settings=<repo>/default_srt_settings.json, working_directory=S/work). Submit code that double-forks a setsid child and then exits normally. The child loops for about 10 s over os.mkdir('x'); os.rmdir('x'); os.symlink('S/dummy_target','x'); os.unlink('x'), ignoring OSError, in its cwd (the run dir). Call run_python_code up to about 50 times. After each call, stat S/dummy_target, and stop at the first mode change to 0o700. Also record whether the child is still alive (pgrep) right after the call returns, and whether os.symlink succeeded inside the sandbox. Use only dummy paths, and kill leftover children afterwards. | Owner-observed on a representative macOS CLI or library install (user=None): run the same bounded procedure against a predeclared dummy directory outside the working directory, and report only (a) whether a detached descendant outlives a normal run and (b) whether the dummy's mode changed to 0700. No real user directories or data, and no production host. |
| On macOS (Seatbelt backend), processes started by sandboxed code outlive the run: nothing kills them on normal exit, a setsid() child escapes the timeout killpg, and survivors that keep stdio pin reader threads and pipe fds in the server | `direct_use.py:60` → `code_executor.py:247` → `code_executor.py:149` → `code_executor.py:160` → `code_executor.py:165` → `code_executor.py:168` → `code_executor.py:267` | Real macOS Seatbelt behaviour was not observed. sandbox-exec cannot run in the approved Linux container sandbox, and target or srt code must not run on the macOS host. From source, srt 0.0.64 macos-sandbox-utils.js:284-287 allows process-fork and process-exec, and cli.js:202-230 spawns with stdio 'inherit' and exits on direct-child exit with no descendant cleanup. However, survival past srt exit and killpg was shown only with a stub srt that has no Seatbelt (agents/h-macos/artifacts/evidence1.txt). The Linux control at current source left no survivors (agents/ver-macdetach/artifacts/evidence1.txt). Deployment-dependent and not established: whether any supported deployment runs the server or CodeSandbox directly on macOS, and whether the server uid has fewer than 256 processes and is not root. On the dev host the uid has 433 processes, so the a80b830 'ulimit -u 256' makes fork() fail with EAGAIN inside the sandbox and blocks the escape there. Not established: the RLIMIT_NOFILE of deployed macOS server processes, which decides whether the leaked pipe fds (2 per detached run) can reach EMFILE. | On a disposable macOS machine with srt 0.0.64, run as a dedicated non-root user with fewer than 256 processes (check with 'ps -U <user> / wc -l'). Use CodeExecutor(settings=CodeSandboxSettings(code_timeout_seconds=2, user=None, working_directory=<empty dir>, path_to_srt_settings=default_srt_settings.json, path_to_python_interpreter=<venv python>)). Case 1 (normal exit): code 'import os\nif os.fork()==0:\n  os.setsid(); os.execv("/bin/sleep",["sleep","4241"])\nprint("x")'. Case 2 (timeout): the same with tag 4242 plus 'import time; time.sleep(60)' in the parent. After each call returns, record the elapsed time, the output, 'pgrep -f "sleep 424[12]"', threading.active_count() and 'lsof -p <server pid> / wc -l'. Case 3: repeat case 1 with os.close(1); os.close(2) in the child to separate survival from the fd leak. The finding is confirmed if any sleeper survives. The fd/thread part is confirmed if fds and threads grow by 2 per run in cases 1 and 2. Run cases 1 and 2 once more as a desktop user with 256 or more processes to record whether fork fails with EAGAIN. Kill all sleepers afterwards. Fix: always os.killpg the group after proc.wait(). On backends without PID isolation (non-Linux), either refuse to run or supervise and kill the full descendant tree (for example, track the session and the processes of the sandbox uid). Close proc.stdout/proc.stderr after the joins. Add tests for the setsid and normal-exit variants. | Owner to confirm whether any supported deployment runs the MCP server or CodeSandbox library directly on macOS rather than in the Linux Docker image. If it does, record the server uid, whether it is root, its typical process count relative to 256, and the server's RLIMIT_NOFILE ('launchctl limit maxfiles' or 'ulimit -n' of the launching shell). If Linux only, document that and consider refusing to start when sys.platform != 'linux'. |

Details: `NEEDS-VALIDATION.md`.

## 5. Hardening notes (not findings)

- **gid 0 inheritance (u21, no finding).** In Docker the sandbox runs as uid 999 but keeps gid 0 from the root server. No group-0-writable target was found. Pass `group=` and `extra_groups=[]` to both `Popen` and `subprocess.run`.
- **Path-based chmod in `_remove_run_dir` (u22 lead).** A no-follow chmod (portably, `chmod -R -P` as in the rmtree fix, since `os.chmod(..., follow_symlinks=False)` is not available on every platform) removes the symlink-following sink. Do **not** switch to `os.open`+`fchmod`: Phase 5 showed that opening a mode-0 directory fails without DAC_OVERRIDE, which regresses the same-uid unlock, and that `os.fwalk` runs out of fds at about 500 levels.
- **Process cleanup on normal exit.** `os.killpg` runs only on timeout. Also kill the group on normal exit, and close the pipes. `_drain` drops partial output when a reader join times out.
- **macOS `ulimit -u`.** On a desktop macOS user the per-uid process limit is shared with the user's whole session, so `ulimit -u 256` can break fork for sandbox code on a busy desktop. It is not a boundary issue, but it is surprising.
- **Output amplification.** Base64 plus JSON inflates returned data about 2.1x over the 200 MB budget. Files are read fully before the budget check; check `fstat().st_size` first.
- **Symlinked `./output`.** It gives a server traceback in the tool result instead of a clean error. Full tracebacks (with server paths) are returned to the client in general, and transient `EAGAIN` is reported as "tool broken".
- **Sensitive logging.** The submitted code and the settings are logged at INFO. Consider DEBUG or truncating them. The same logger also needs `repr_native_str=True` (see the terminal-escape finding).
- **srt settings temp file.** One `mkstemp` file leaks per `CodeExecutor` process. It is harmless.
- **Shared views in Docker.** `/proc` shows other runs' cmdlines (uuid run paths), and `/tmp` lists other runs' srt sockets. Neither discloses secrets.
- **CLI defaults.** `working_directory` defaults to the cwd, so `denyRead` of the cwd can cover the CLI's own `.venv`. `cli.py:106` quotes dependencies incorrectly (functional).
- **stdio transport (functional).** `mcp_server.py` always passes host, port and path, so `--mcp_transport stdio` crashes with a `TypeError`.
- **Build and release.** There is no `.dockerignore`, so `.git` is baked into the image. Pin GitHub Actions by SHA, and pin base images and the srt version. Add an environment protection gate to the `docker_hub` publish job. Use `--chown`/root ownership for `/code` and `/sandbox`.
- **README `docker run`.** Unlike compose, the documented `docker run` sets no `--memory` or `--pids-limit`.

### Positive source patterns

- The a80b830 fixes for the three run-2 findings hold. `stdin=subprocess.DEVNULL` closes the stdin/terminal inheritance. `unshare --ipc` gives each Linux run a fresh IPC namespace, which closes the SysV cross-run leak. `denyWrite` on srt's implicit write paths closes the shared `/tmp/claude` channel. All three were revalidated in this run (critic-w1 plus wave-1 hunters).
- Output reads stay `O_NOFOLLOW`, use fd-relative access and `fstat` checks, and now have a 200 MB aggregate byte budget.
- Per-run `denyRead` isolation, process-group kill on timeout, `finally` cleanup and the 1 MB caps on stdout and stderr all held on Linux/Docker.
- In Docker, the user-namespace wrapper makes `ulimit -u` a per-run cap rather than a per-uid cap, and compose now sets `pids_limit`, `mem_limit` and `cpus`.

## 6. Coverage

- Ledger: 22 units — 8 candidate, 14 covered. The ledger validator passes, and so does the findings validator.
- Every candidate fingerprint was independently validated in Phase 3, and every retained record passed a fresh Phase 5 review. Only the rmtree record changed: Phase 5 replaced its remediation (the fwalk/fchmod fix was shown to regress the same-uid unlock and to run out of fds), and a further fresh verifier re-checked the replacement. That verifier made one last narrow correction: `--` must come before the chmod mode operand for BSD/macOS, and it added an OSError guard. It tested the correction with GNU coreutils in the sandbox and with the system BSD `chmod`/`rm` binaries on the host (dummy scratch files only; no target code ran on the host). The correction changes neither claim, evidence nor severity, so it was applied without another review loop. Phase 3 corrected the resource-limits mechanism: the hunter's per-uid claim was refuted, and the confirmed cause is per-run caps not sized against the pool. It also widened the u22 lead from directories to directories and regular files.
- Phase 5 was asked to check the resource-limits and admission records for duplication. Both were kept as distinct root causes: pid-pool exhaustion makes runs fail, while the thread pool makes them queue. They belong to the same fix family.
- Rejected in this run: 0.
- Wave 1 covered u1–u20. Critic-w1 added u21 (gid 0; covered, no finding) and u22 (macOS chmod TOCTOU). Critic-w2 and the distinct final-clean critic both returned **clean** (no missing units, no reassignments).
- This is one pass. It does not exhaust the target, and the macOS runtime behaviour remains source-derived (see NEEDS-VALIDATION.md).