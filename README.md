# ISO 26262 Validation Tool

Claude-powered validation of engineering work products across the right side of the
V-model (SW integration test, system test, validation test, release). Local-first,
no SaaS lock-in.

## Status

**Phase 1 complete** — knowledge base ingestion (CSV / Excel / Cradle XML → SQLite + ChromaDB).

See `docs/ROADMAP.md` (generated from this README) for phase plan.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY

# Ingest the sample artefacts
python -m src.cli ingest samples/

# Inspect the KB
python -m src.cli stats
```

## Architecture

```
CLI / Web UI
    │
    ▼
Orchestrator ── Ingestion ── SQLite (structured: requirements, test_cases, defects, trace_links)
    │         └ Chroma    (semantic: embeddings for requirements, TCs, standards clauses)
    │
    ▼
Validation Engine ── Anthropic SDK (claude-opus-4-7, adaptive thinking, prompt caching)
    │                 Structured outputs via messages.parse()
    ▼
Report / Export (CSV, Excel, optional Cradle-ready)
```

**Design rule — no hallucinated validation.** Every verdict and every generated
test case must cite the exact requirement text span it is grounded in. If no
grounding can be extracted (ambiguous / untestable requirement), the engine
flags the requirement instead of guessing.

## Phased roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | KB ingestion (CSV/Excel/Cradle → SQLite + Chroma), CLI, samples | ✅ |
| 2 | Validation engine: coverage, testability, SG→TSR→SSR→test traceability | ⏳ |
| 3 | Web UI (FastAPI + htmx): upload → validate → results | ⏳ |
| 4 | Test case generation (grounded), CSV/Excel/Cradle export | ⏳ |

## Tech choices

- **Python 3.11+** — rich RAG ecosystem, first-class Anthropic SDK.
- **SQLite + ChromaDB** — hybrid store. SQLite for IDs, joins, trace links;
  Chroma for semantic similarity. Both on-disk, no server, no lock-in.
- **`sentence-transformers/all-MiniLM-L6-v2`** — local embeddings, free.
- **`claude-opus-4-7`** for validation reasoning (adaptive thinking), configurable
  to `claude-haiku-4-5` for bulk ambiguity screening. Prompt caching used for
  standards clauses and the validation system prompt.
- **Pydantic v2** — typed KB schemas, structured LLM outputs.
- **Typer** (CLI), **FastAPI + htmx** (Phase 3 UI).

## Extending beyond ISO 26262

The KB schema and validation prompts are parameterised by a "standard pack"
(see `src/engine/prompts.py`). Ship an ASPICE or generic-SDLC pack by adding a
new system-prompt module and clause-set under `samples/standards/`. Nothing in
the core ingestion or engine is 26262-specific.

## Sample data

`samples/` contains toy requirements, test cases, defects, and a safety-goal
chain (SG → TSR → SSR → test) so you can exercise the ingestion + later the
validation engine without real project data.

## Configuration

See `.env.example`. Key knobs:

- `ANTHROPIC_API_KEY` — required.
- `VALIDATION_MODEL` — default `claude-opus-4-7`.
- `SCREENING_MODEL` — default `claude-haiku-4-5`, used for cheap per-req
  classification passes.
- `KB_DIR` — where SQLite + Chroma live (default `./kb_data`).
