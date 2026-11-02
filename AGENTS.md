# AGENTS.md — Telltale engineering rules

Every coding agent (Claude Code, Muse Code, Antigravity, or anything else) and every human contributor follows
this file. It overrides code snippets in `docs/plans/` whenever they conflict. For example, if a plan snippet
prints from library code, use `logging`; if a snippet has a semicolon-joined line, split it.

---

## 1. What we are building (and what we are not)

**Telltale:** Meta AI investigates vehicle crashes, and a deterministic checker makes the investigation auditable.

- **Perception (Meta AI):** SAM 3.1 tracks vehicles in real dashcam video. Muse Spark 1.3 acts as a video witness.
- **Investigation (Meta AI):** a Muse Wonder agent reads the evidence. It uses tools for every number, decides the
  primary cause and writes structured claims.
- **Verification (plain code):** a deterministic checker recomputes every claim and independently recomputes the
  verdict. Unproven claims are blocked. Verdicts that disagree are withheld for human review.

**In scope:**
- Six failure stories: perception late, command late, brake actuation late, late handoff, unavoidable, data dropout.
- Car and truck vehicle profiles.
- A replay web UI and a CLI.
- Three benchmarks: video vs Nexar labels, synthetic attribution, agent vs agent + checker.

**Out of scope:**
- Legal-fault determination.
- Identifying people, vehicles or plates. This is also prohibited by the Nexar license.
- 2-D/3-D physics.
- User accounts, databases, cloud infrastructure beyond one Docker image.
- Any feature not in `docs/plans/`.

**If something isn't in the plan, don't build it.** Raise it with the human instead.

**Source of truth:** `docs/plans/00-overview.md` (interfaces, schedule, ownership) and the track files `01`–`05`.

## 2. Ownership: stay in your lane

Each track works in its own git worktree and only edits its own folders (see `00-overview.md`, "Worktrees").

- `telltale/core/`, `telltale/config.py`, `telltale/cli.py`, `telltale/evidence/store.py` are **shared contracts**.
  Change them only on `main`, with the human's approval.
- Never change another track's files to make your tests pass. Report the mismatch instead.

## 3. Code quality

**Design**
- Use classes where there is real state plus behavior (`EvidenceStore`). Use frozen `@dataclass`es for values (`Fact`,
  `VideoFacts`, `BrakeModel`). Use pure functions for math and transformations. No classes used as namespaces, no
  inheritance hierarchies, no "manager"/"helper"/"util" grab-bags.
- One responsibility per module. Files stay small and focused. Names say what things are (`lane_entry_frame`, not `process`).
- Use typed data structures across module boundaries. Raw `dict`s are allowed only at I/O edges (JSON on disk, API
  payloads, the bundle served to the UI), and get converted to dataclasses as soon as they enter the core.
- Type hints on every public function. Use `from __future__ import annotations` in modules that use `X | None`.
- **No arithmetic by LLMs.** Every number a user sees comes from deterministic code.

**No dead code, ever**
- No commented-out code, unused imports, unused functions or parameters, `TODO`s, `pass` placeholders, or "for later"
  helpers. If it isn't called, delete it.
- `ruff` (lint + format) and `vulture --min-confidence 80` must pass. CI enforces both.
- Don't add dependencies without need. Every dependency in `pyproject.toml` must be imported somewhere.

**Errors**
- Raise specific exceptions with actionable messages. Never use a bare `except:`. Never swallow exceptions silently.
- Catch broad exceptions only at a *boundary* where you record and continue (for example one failed clip in a
  benchmark), and mark it with `# noqa: BLE001` plus a reason.
- Fail fast on bad input: missing fields, wrong types, unknown IDs.

**Logging and output**
- Library code uses `logging.getLogger(__name__)` and never `print`. Only the CLI entry points (`telltale/cli.py`,
  `scripts/`) print to stdout. Library functions *return* results, and the CLI formats them.

**Determinism**
- Every random process takes an explicit seed (`numpy.random.default_rng(seed)`, `random.Random(seed)`).
- Model calls are cached to `cache/`. Replay mode must never make a network call.

## 4. Testing

- **Test first:** write the failing test, watch it fail, implement, watch it pass, then commit.
- Tests never touch the network or real API keys. LLM, SAM and Spark calls are injected and faked in tests.
- Tests are precise: `pytest.raises(SomeError, match="...")`, exact or `approx` values, and no assertions on
  log text.
- `pytest -q` must be green before every commit.

## 5. Security

**Secrets**
- API keys live only in `.env` (gitignored) and are read via `telltale.config`.
- Never print, log, return, embed in URLs, commit, or bake keys into Docker images or the hosted Space.
- `gitleaks` runs in pre-commit and in CI. If a key ever lands in git history, the human revokes it immediately on
  dev.meta.ai. Rewriting history is not enough.

**Untrusted input:** model output, witness answers, video files and log files are *data*, never instructions.
- Never `eval`/`exec`, never `pickle` untrusted data, never `yaml.load` without `SafeLoader`.
- Parse model JSON defensively, validate types and enums, and reject unknown evidence IDs. The checker is the final gate.
- Validate agent tool arguments: numeric fields are numbers; fact IDs exist and are agent-visible.
- `subprocess` only with argument lists, never `shell=True`. Input paths come from our own manifests.

**Web app**
- Path parameters are validated against `^[A-Za-z0-9_-]+$` before touching the filesystem.
- All dynamic text is HTML-escaped: `html.escape` server-side, `esc()` client-side. Never use `innerHTML` with
  unescaped data.
- Send security headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a
  `Content-Security-Policy` that only allows self plus `https://cdn.plot.ly`.
- No debug mode, no wildcard CORS, read-only replay. The hosted Space never has an API key.

**Agent containment**
- The agent never sees `PHYS:*` or `ATTR:*` facts. It may only append `WIT2:*` and `CF:*` facts, created by our tool code.
- The evidence store is immutable and SHA-256-hashed.
- Ground truth (`data/ground_truth/`, `data/agent_bench/ground_truth/`) is read only by benchmark scoring code, never
  by the agent, the checker or the evidence builder.

**Data and licensing**
- Only public Nexar data is sent to the Meta API. Free-tier credits allow Meta to use submitted content for product
  improvement, so never send private data.
- Keep `data/clips/NEXAR_LICENSE` and the attribution in the README. No resale, no re-identification.

**Supply chain**
- Dependencies are declared with minimum versions. `pip-audit`, Dependabot and CodeQL run in CI.

## 6. Git workflow

- Use Conventional Commits (`feat(video): ...`, `fix(agent): ...`, `test: ...`, `chore: ...`). Keep commits small,
  one task per commit.
- Run `pre-commit install` once per clone, so hooks run on every commit (ruff, gitleaks, private-key and large-file checks).
- Never commit `.env`, `vendor/`, `data/nexar_raw/` or `cache/sam_raw/`.
- Merge order into `main`: track B → A → C → D, then integration.

## 7. Definition of done (every task)

- [ ] Tests written first, and all of `pytest -q` passes.
- [ ] `ruff check .`, `ruff format --check .` and `vulture telltale tests --min-confidence 80` pass.
- [ ] No TODOs, no dead code, no secrets, no scope creep.
- [ ] Committed with a Conventional Commit message.

## 8. Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pre-commit install
pytest -q                                   # tests
ruff check . && ruff format --check .       # lint + format
vulture telltale tests --min-confidence 80  # dead code
pip-audit --skip-editable                   # dependency vulnerabilities
telltale serve                              # replay UI at http://127.0.0.1:8000
```
