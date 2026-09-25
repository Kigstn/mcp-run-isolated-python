# Security audit — commit a80b830 (2026-09-25)

Source-first audit with Claude Code's security-audit skill. Target code only ran in a local, network-less Docker sandbox; no deployed instances were tested.

- [REPORT.md](REPORT.md) — summary, all findings, hardening notes, coverage
- [FINDINGS-DETAIL.md](FINDINGS-DETAIL.md) — full detail for the medium findings
- [NEEDS-VALIDATION.md](NEEDS-VALIDATION.md) — unconfirmed leads (macOS only)
- `findings.json`, `coverage-ledger.json`, `architecture.md` — machine-readable results
- `agents/*/artifacts/evidence*.txt` — evidence referenced by the findings

## Status

| Finding | Severity | Status |
|---|---|---|
| HTTP transport accepts any Host/Origin, no auth | medium | Host/Origin check added (`MCP_ALLOWED_HOSTS` for extra names). Authentication is left to the deployment, e.g. a reverse proxy |
| Per-run process caps not sized against the container pid pool | medium | Fixed: max 4 concurrent runs × 64 processes |
| Deep directory tree survives run dir cleanup | medium | Fixed: cleanup errors are caught, `chmod -R` / `rm -rf` fallback |
| No concurrent-run admission control | low | Partly: the same cap bounds concurrent runs, extra runs wait in a queue. One client can still delay others (no per-client fairness) |
| Zero-byte output files bypass the output budget | low | Open |
| Output file names logged raw (terminal escapes) | low | Open |
| srt temp files left in `/tmp` | low | Open |
| macOS: sandbox descendants outlive the run / chmod race in cleanup | needs validation | Won't fix — macOS is not a supported production platform |
