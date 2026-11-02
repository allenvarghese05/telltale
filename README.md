---
title: Telltale
emoji: 🚦
colorFrom: gray
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

# Telltale

**Meta AI investigates vehicle crashes. A deterministic checker makes the investigation auditable.**

SAM 3.1 and Muse Spark read real dashcam footage. A Muse Wonder agent investigates the vehicle's logs and
decides the primary cause. Every claim it makes, and the verdict itself, is independently recomputed by code
before anyone sees it.

> 🚧 In active development for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
> The plan lives in [`docs/plans/`](docs/plans/), and contributor rules are in [`AGENTS.md`](AGENTS.md).

## Develop
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pre-commit install
cp env.example .env        # add MODEL_API_KEY (never commit .env)
pytest -q
```

## Data
Video comes from the Nexar Collision Prediction Dataset, under the Nexar Open Data License. Attribution: Moura &
Zvitia, "Nexar Collision Dataset", Hugging Face, 2025.
