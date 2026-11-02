# Security policy

## Reporting
Please report vulnerabilities privately via GitHub's **Report a vulnerability** (Security tab). Do not open a
public issue for security problems.

## What we protect
- **API keys:** they live only in a local `.env` (gitignored). They are never logged, committed, or deployed. The
  hosted demo is replay-only and holds no key. If a key leaks, revoke it on dev.meta.ai immediately.
- **Integrity of findings:**
  - Evidence is stored immutably with a SHA-256 digest.
  - The investigator agent cannot see the checker's derived facts.
  - It may only append facts produced by our own tool code.
  - Every claim and the verdict are recomputed by a deterministic checker before they reach a report.
- **Untrusted input:** model output, video and log files are treated as data. There is no `eval`/`exec`, no
  `shell=True`, path parameters are validated, and all rendered text is HTML-escaped.

## Automated checks (CI)
- **gitleaks:** secret scanning over the full git history (also as a pre-commit hook).
- **ruff `S` rules:** Bandit-equivalent static security lint.
- **CodeQL:** `security-extended` queries for Python and JavaScript.
- **pip-audit:** known-vulnerable dependencies. Dependency Review runs on pull requests, and Dependabot runs weekly.
