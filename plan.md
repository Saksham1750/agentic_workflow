# AI Agent Factory v2 - Phase-Wise Implementation Plan

## Overview
This plan covers all 7 milestones for building a backend-only AI agent factory that converts BRD/PRD/TRD documents into working code through three sequential agentic workflows with Human-in-the-Loop (HITL) via WebSockets.

**Tech Stack:** FastAPI, LangGraph, OpenAI (GPT-5.5/5.4), SQLite + SQLAlchemy (async), ChromaDB, JWT Auth, SSE, WebSockets

---

## Milestone Dependencies & Execution Order

```
M1: Foundation & Document Ingestion (REQUIRED FIRST)
    ↓
M2: Pattern Knowledge Base (CAN PARALLEL WITH M3 AFTER M1)
    ↓
M3: Workflow 1 - Requirements Gathering (REQUIRES M1, M2)
    ↓
M4: Workflow 2 - Combined Planning (REQUIRES M3 COMPLETE)
    ↓
M5: Workflow 3 - Code Generation (REQUIRES M4 COMPLETE)
    ↓
M6: Orchestration, Resumability & Streaming (CROSS-CUTTING - APPLY TO ALL)
    ↓
M7: Observability & Traceability (FINAL POLISH)
```

**Critical Path:** M1 → M3 → M4 → M5 → M6 → M7 (M2 can run in parallel with M3 after M1)

---

## MILESTONE 1: Foundation & Document Ingestion

**Goal:** FastAPI backend, persistence, file storage, document ingestion pipeline

### Phase 1.1: Project Setup & Configuration
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 1.1.1 | Initialize FastAPI project structure | `pyproject.toml`, `requirements.txt`, `src/` layout | `pip install -e .` succeeds |
| 1.1.2 | Create config module with 12-factor env vars | `src/config.py`, `.env.example` | All config via env vars; no secrets in code |
| 1.1.3 | Set up SQLite + SQLAlchemy async models | `src/models/`, `src/database.py` | Tables created via Alembic/migrate |
| 1.1.4 | Implement JWT authentication | `src/auth/`, `src/middleware/auth.py` | `POST /auth/login` returns JWT; protected routes return 401 |
| 1.1.5 | Create FileStore abstraction | `src/storage/file_store.py` | CRUD operations on `./data/projects/{project_id}/` |
| 1.1.6 | Health check endpoint | `src/routers/health.py` | `GET /healthz` checks SQLite, ChromaDB, filesystem |
| 1.1.7 | Structured error handling + Swagger | `src/exceptions.py`, `src/main.py` | Swagger at `/docs` shows all endpoints; error envelope format |

### Phase 1.2: Project & Document CRUD
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 1.2.1 | Project lifecycle endpoints | `src/routers/projects.py` | POST/GET/PATCH `/projects`; status transitions |
| 1.2.2 | Document upload endpoint | `src/routers/documents.py` | Multipart upload; 415 for unsupported MIME; 413 for oversize |
| 1.2.3 | Idempotent upload (content hash) | `src/services/document_service.py` | Same content returns existing document_id |
| 1.2.4 | Document status & sections endpoints | `src/routers/documents.py` | GET status, sections, outline |
| 1.2.5 | Project-scoped authorization | `src/middleware/auth.py` | Cross-project access returns 404 |

### Phase 1.3: Document Parsing & Embedding Pipeline
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 1.3.1 | Parser factory for all MIME types | `src/services/parsers/` (pdf, docx, pptx, xlsx, md, txt) | Each parser extracts heading-aware sections |
| 1.3.2 | Async background parse job | `src/services/document_service.py`, `src/tasks/` | Background task kicks off; status updates |
| 1.3.3 | ChromaDB client + collections setup | `src/vectorstore/chroma_client.py` | `documents` and `patterns` collections created |
| 1.3.4 | Chunking + embedding pipeline | `src/services/embedding_service.py` | Chunks upserted with metadata (project_id, document_id, section_id) |
| 1.3.5 | Project-scoped RAG query helper | `src/services/rag_service.py` | Queries filtered by project_id |

### Phase 1.4: Testing & Documentation
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 1.4.1 | Unit tests for parsers, auth, FileStore | `tests/unit/test_m1_*` | 80% coverage on changed files |
| 1.4.2 | Integration test: upload → parse → embed | `tests/integration/test_m1_flow.py` | End-to-end with real SQLite + ChromaDB |
| 1.4.3 | README quickstart for M1 | `README.md` | `curl` commands for auth, project, upload work |

---

## MILESTONE 2: Agentic Design Patterns Knowledge Base

**Goal:** Searchable, embedding-indexed Pattern KB with CRUD and seed content

### Phase 2.1: Pattern Schema & Persistence
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 2.1.1 | Pattern Pydantic models + SQLAlchemy | `src/models/pattern.py` | Schema matches spec (name, intent, structure, when_to_use, etc.) |
| 2.1.2 | Pattern CRUD endpoints | `src/routers/patterns.py` | POST/GET/PATCH/DELETE `/patterns` |
| 2.1.3 | Bulk import (JSON/YAML) | `src/routers/patterns.py` | `POST /patterns/bulk` accepts array or YAML file |

### Phase 2.2: Embedding & Search
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 2.2.1 | Pattern embedding on create/update | `src/services/pattern_service.py` | Embedded into ChromaDB `patterns` collection |
| 2.2.2 | Search endpoint with filters | `src/routers/patterns.py` | `POST /patterns/search` returns ranked results with scores |
| 2.2.3 | Tag-based filtering | `src/services/pattern_service.py` | Search respects tags filter |

### Phase 2.3: Seed Content & Testing
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 2.3.1 | Seed 10+ canonical patterns | `src/seeds/patterns.yaml` | ReAct, Reflection, Planner-Executor, Multi-Agent Debate, Router, RAG, Tool-Use, Hierarchical, Critic-Refine, Map-Reduce |
| 2.3.2 | Idempotent seeding on startup | `src/main.py` lifespan | Patterns exist after restart; no duplicates |
| 2.3.3 | Unit/integration tests | `tests/unit/test_m2_*`, `tests/integration/test_m2_flow.py` | Search returns relevant patterns |

---

## MILESTONE 3: Workflow 1 - Requirements Gathering

**Goal:** LangGraph workflow with Reflection pattern, WebSocket HITL, checkpointing

### Phase 3.1: LangGraph Infrastructure
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 3.1.1 | Base workflow state schema | `src/workflows/requirements/state.py` | State with reducers for messages, clarifications, requirements |
| 3.1.2 | SQLite checkpointer setup | `src/workflows/checkpointer.py` | `AsyncSqliteSaver` connected to `./data/checkpoints.sqlite` |
| 3.1.3 | Graph visualization endpoint | `src/routers/workflows.py` | `GET /workflows/requirements/graph.png` returns PNG |

### Phase 3.2: Core Workflow Nodes
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 3.2.1 | Document ingestion node | `src/workflows/requirements/nodes.py` | Loads approved documents from ChromaDB |
| 3.2.2 | Gap analysis node (Reflection) | `src/workflows/requirements/nodes.py` | Self-critique identifies missing requirements |
| 3.2.3 | Clarification generator node | `src/workflows/requirements/nodes.py` | Produces structured questions for HITL |
| 3.2.4 | Requirements synthesizer node | `src/workflows/requirements/nodes.py` | Outputs Markdown + JSON Requirements Document |
| 3.2.5 | Validation node | `src/workflows/requirements/nodes.py` | Checks completeness before approval |

### Phase 3.3: WebSocket HITL Channel
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 3.3.1 | WebSocket endpoint with JWT auth | `src/websockets/hitl.py` | `WS /projects/{pid}/runs/{rid}/hitl` validates token at handshake |
| 3.3.2 | Clarification request/response protocol | `src/websockets/hitl.py`, `src/schemas/hitl.py` | JSON envelope with type, request_id, payload |
| 3.3.3 | Graph interrupt + resume via Command | `src/workflows/requirements/graph.py` | `interrupt_before` on clarification node; `Command(resume=...)` resumes |
| 3.3.4 | Max rounds limit (configurable, default 3) | `src/workflows/requirements/graph.py` | Cap exceeded → `clarification_failed` |
| 3.3.5 | Socket reconnection handling | `src/websockets/hitl.py` | Pending request re-sent with same request_id |
| 3.3.6 | REST fallback endpoints | `src/routers/runs.py` | POST clarifications, approve, reject |

### Phase 3.4: Approval Gate
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 3.4.1 | Approval interrupt node | `src/workflows/requirements/graph.py` | `interrupt_before` on approval node |
| 3.4.2 | Approval request/response over WS | `src/websockets/hitl.py` | approval_request → approval_response (approve/reject+feedback) |
| 3.4.3 | Rejection feedback injection | `src/workflows/requirements/graph.py` | Feedback written to state; graph resumes from prior node |

### Phase 3.5: Run Management & Output
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 3.5.1 | Workflow trigger endpoint | `src/routers/workflows.py` | `POST /projects/{pid}/workflows/requirements` → 202 + run_id |
| 3.5.2 | Idempotency key + single-run lock | `src/services/run_service.py` | 409 if active run exists; Idempotency-Key replay returns same run_id |
| 3.5.3 | Run status + SSE events | `src/routers/runs.py`, `src/services/sse_service.py` | GET status; SSE stream with node_started/completed events |
| 3.5.4 | Artifact persistence | `src/services/artifact_service.py` | Requirements MD + JSON saved to `./data/projects/{pid}/runs/{rid}/` |
| 3.5.5 | Integration test full flow | `tests/integration/test_m3_flow.py` | Upload docs → trigger → clarify → approve → artifact produced |

---

## MILESTONE 4: Workflow 2 - Combined Project & Code Planning

**Goal:** Multi-agent planning with pattern selection, multi-source research, architecture, task planning, validation

### Phase 4.1: Workflow 2 State & Graph Structure
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 4.1.1 | Planning workflow state schema | `src/workflows/planning/state.py` | State with requirements, patterns, research, architecture, tasks, validation |
| 4.1.2 | Subgraph: Researcher (parallel branches) | `src/workflows/planning/subgraphs/researcher.py` | 3 parallel branches: doc RAG, KB RAG, web search; join via reducer |
| 4.1.3 | Subgraph: Planner-Critic (Evaluator-Optimizer) | `src/workflows/planning/subgraphs/planner_critic.py` | Cycle with iteration counter; generator → evaluator → revise |
| 4.1.3 | Router node (complexity-based) | `src/workflows/planning/nodes/router.py` | Routes to lightweight vs heavyweight planning path |
| 4.1.4 | Parent graph composition | `src/workflows/planning/graph.py` | Orchestrator-Worker: Supervisor → PatternSelector → Researcher → Architect → Planner-Critic |

### Phase 4.2: Specialist Agents
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 4.2.1 | Pattern Selector agent | `src/workflows/planning/agents/pattern_selector.py` | Queries KB; returns minimal pattern set with rationale + requirement mapping |
| 4.2.2 | Researcher agent (multi-source) | `src/workflows/planning/agents/researcher.py` | RAG(doc) + RAG(KB) + web_search + LLM; all claims cited |
| 4.2.3 | Architect agent | `src/workflows/planning/agents/architect.py` | Produces architecture doc (MD + JSON) with components, data flow, risks |
| 4.2.4 | Planner agent | `src/workflows/planning/agents/planner.py` | Decomposes architecture into ordered task list with deps, acceptance criteria, pattern refs |
| 4.2.5 | Critic/Validator agent | `src/workflows/planning/agents/critic.py` | Checks coverage, ordering, pattern fidelity, atomicity; returns pass/fail + feedback |

### Phase 4.3: WebSocket Approval & Task Editing
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 4.3.1 | Approval interrupt for task list | `src/workflows/planning/graph.py` | `interrupt_before` on approval node |
| 4.3.2 | Task list CRUD endpoints | `src/routers/tasks.py` | GET tasks, PATCH task (edit, reorder, split with dep validation) |
| 4.3.3 | Rejection feedback loop | `src/workflows/planning/graph.py` | Feedback injected; graph revises from planner node |

### Phase 4.4: Output Artifacts & Testing
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 4.4.1 | Persist all artifacts | `src/services/artifact_service.py` | Patterns report, research log, architecture, task list |
| 4.4.2 | Trigger endpoint + status/SSE | `src/routers/workflows.py`, `src/routers/runs.py` | POST planning → 202; GET status; SSE events |
| 4.4.3 | Graph visualization | `src/routers/workflows.py` | `GET /workflows/planning/graph.png` |
| 4.4.4 | Integration test full planning flow | `tests/integration/test_m4_flow.py` | Requirements → patterns → research → architecture → tasks → approve |

---

## MILESTONE 5: Workflow 3 - Code Generation

**Goal:** Orchestrator-Worker developer agent with dynamic subgraphs, reviewer sub-agents, bundle download

### Phase 5.1: Codegen Workflow Structure
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 5.1.1 | Codegen state schema | `src/workflows/codegen/state.py` | State with task list, current_task_index, workspace_files, review_results |
| 5.1.2 | Top-level orchestrator graph | `src/workflows/codegen/graph.py` | Plan-and-Execute: iterates task list sequentially |
| 5.1.3 | Dynamic per-task subgraph builder | `src/workflows/codegen/subgraph_builder.py` | Builds subgraph based on task.pattern_refs (Reflection → critic cycle; Tool-Use → ToolNode) |
| 5.1.4 | Developer agent (orchestrator) | `src/workflows/codegen/agents/developer.py` | Reads requirements, architecture, task, pattern refs; writes files via FileStore |

### Phase 5.2: Reviewer Sub-Agents (Parallel)
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 5.2.1 | Workflow reviewer | `src/workflows/codegen/agents/reviewers.py` | Checks agent orchestration matches selected patterns |
| 5.2.2 | Prompt reviewer | `src/workflows/codegen/agents/reviewers.py` | Checks prompt clarity, role, injection resistance |
| 5.2.3 | Security reviewer | `src/workflows/codegen/agents/reviewers.py` | OWASP basics: input validation, secrets, error leakage |
| 5.2.4 | Parallel execution + reducer | `src/workflows/codegen/subgraph_builder.py` | All 3 run in parallel; verdicts reduced to pass/fail + feedback |

### Phase 5.3: Retry Loop & Bundle
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 5.3.1 | Developer-Reviser cycle (Evaluator-Optimizer) | `src/workflows/codegen/subgraph_builder.py` | On reviewer fail, developer iterates with feedback (configurable cap) |
| 5.3.2 | Workspace file management | `src/storage/file_store.py` | Files written to `./data/projects/{pid}/runs/{rid}/workspace/` |
| 5.3.3 | Bundle creation + download | `src/services/artifact_service.py` | ZIP → `bundle.zip`; `GET /artifacts` streams FileResponse |
| 5.3.4 | MANIFEST.json generation | `src/services/artifact_service.py` | Maps task_id → file paths |

### Phase 5.4: Approval & Testing
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 5.4.1 | Final approval interrupt | `src/workflows/codegen/graph.py` | `interrupt_after` final task → approval_request over WS |
| 5.4.2 | REST approve endpoint | `src/routers/runs.py` | POST approve marks project completed |
| 5.4.3 | Integration test full codegen | `tests/integration/test_m5_flow.py` | Approved tasks → codegen → review → bundle → approve |

---

## MILESTONE 6: Orchestration, Resumability & Streaming

**Goal:** Production-grade cross-cutting infrastructure for all workflows

### Phase 6.1: Checkpointing & Resumability
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 6.1.1 | Unified checkpointer for all workflows | `src/workflows/checkpointer.py` | Single `AsyncSqliteSaver` at `./data/checkpoints.sqlite` |
| 6.1.2 | Resume endpoint | `src/routers/runs.py` | `POST /projects/{pid}/runs/{rid}/resume` restarts from last checkpoint |
| 6.1.3 | Crash recovery test | `tests/integration/test_m6_resume.py` | Kill process mid-run; restart → resumes from last node |

### Phase 6.2: SSE Event Streaming
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 6.2.1 | SSE endpoint with Last-Event-ID | `src/routers/runs.py` | `GET /projects/{pid}/runs/{rid}/events` |
| 6.2.2 | Event persistence (run_events table) | `src/models/run_event.py`, `src/services/sse_service.py` | Events stored; reconnect replays from Last-Event-ID |
| 6.2.3 | Typed event emission | `src/services/sse_service.py` | node_started, node_completed, tool_called, tokens_used, clarification_requested, error, run_completed |

### Phase 6.3: WebSocket HITL Hardening
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 6.3.1 | JWT at handshake (subprotocol + query) | `src/websockets/hitl.py` | 401 on missing/invalid; 403/404 on ownership mismatch |
| 6.3.2 | Single subscriber enforcement | `src/websockets/hitl.py` | 2nd connection forces 1st closed with 409 |
| 6.3.3 | Ping/pong liveness (20s/10s) | `src/websockets/hitl.py` | Disconnect closes socket; run stays paused |
| 6.3.4 | Idempotent request/response | `src/websockets/hitl.py` | Duplicate responses ignored; reconnect re-sends same request_id |
| 6.3.5 | Unexpected message handling | `src/websockets/hitl.py` | Server replies `unexpected_message` + closes 400 |

### Phase 6.4: Concurrency & Idempotency
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 6.4.1 | Per-project asyncio.Lock | `src/services/run_service.py` | One active run per project |
| 6.4.2 | Idempotency-Key header support | `src/middleware/idempotency.py` | Replay returns original run_id |
| 6.4.3 | Cost/token ceilings per run | `src/services/cost_guard.py` | Configurable caps; fail with `failed_cost_ceiling` |

### Phase 6.5: Hook Layer (Observability Backbone)
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 6.5.1 | Pre-node hook | `src/workflows/hooks.py` | Log entry, start timer, emit SSE node_started |
| 6.5.2 | Post-node hook | `src/workflows/hooks.py` | Record tokens/cost to usage table, emit SSE node_completed, persist snapshot |
| 6.5.3 | Error hook | `src/workflows/hooks.py` | Emit SSE error; mark run state; re-raise |
| 6.5.4 | Apply hooks to all 3 workflows | `src/workflows/*/graph.py` | Every node wrapped; no ad-hoc logging in nodes |

### Phase 6.6: Graph Visualization
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 6.6.1 | Mermaid/PNG render endpoint | `src/routers/workflows.py` | `GET /workflows/{name}/graph.png` cached on disk |
| 6.6.2 | README embeds 3 diagrams | `README.md` | Diagrams visible in README |

---

## MILESTONE 7: Observability & Traceability

**Goal:** Per-run cost transparency + end-to-end traceability

### Phase 7.1: Token Tracing & Cost Accounting
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 7.1.1 | TokenTracer middleware | `src/observability/token_tracer.py` | Wraps all LLM calls; extracts usage; computes cost from pricing table |
| 7.1.2 | Usage table + persistence | `src/models/usage.py` | run_id, project_id, node, tool, model, tokens_in/out, cost_usd, timestamp |
| 7.1.3 | Usage query endpoints | `src/routers/runs.py` | GET `/runs/{rid}` (totals), GET `/runs/{rid}/usage` (breakdown) |
| 7.1.4 | Configurable pricing table | `src/config.py` | `MODEL_PRICING` env var or config file |

### Phase 7.2: Traceability Artifact
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 7.2.1 | Traceability endpoint | `src/routers/traceability.py` | `GET /projects/{pid}/traceability` returns JSON map |
| 7.2.2 | Mapping: doc.section → requirement → pattern → task → file | `src/services/traceability_service.py` | All 4 link types queryable |
| 7.2.3 | Research log with citations | `src/routers/runs.py` | `GET /projects/{pid}/runs/{rid}/research` returns cited findings |

### Phase 7.3: Audit Log
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 7.3.1 | Audit log table + middleware | `src/models/audit.py`, `src/middleware/audit.py` | Records run_created, approved, rejected, resumed with timestamp + actor |
| 7.3.2 | Audit query endpoint | `src/routers/audit.py` | Project-scoped audit trail |

### Phase 7.4: Final Testing & Documentation
| Task | Description | Files/Components | Verification |
|------|-------------|------------------|--------------|
| 7.4.1 | Full E2E integration test | `tests/integration/test_m7_full_pipeline.py` | All 3 workflows end-to-end with sample BRD |
| 7.4.2 | Load/concurrency tests | `tests/load/` | Multiple projects, concurrent runs (separate projects) |
| 7.4.3 | Complete README | `README.md` | Quickstart, env matrix, curl examples for all workflows, diagram embeds |
| 7.4.4 | Verify all mandatory concepts | `docs/concept_coverage.md` | Checklist: all 5 agent patterns, 6 LangGraph fundamentals, 8 LangGraph advanced features |

---

## Technical Decisions Needed Upfront

| Decision | Options | Recommendation |
|----------|---------|----------------|
| OpenAI Model | GPT-5.5 vs GPT-5.4 | Use GPT-5.5 for planning (reasoning), GPT-5.4 for codegen (speed/cost) |
| Web Search Tool | OpenAI built-in vs custom | Use OpenAI built-in `web_search` tool |
| Background Jobs | FastAPI BackgroundTasks vs Celery | FastAPI BackgroundTasks (simpler, single-process scope) |
| ChromaDB Mode | In-memory vs Persistent | Persistent (`CHROMA_PERSIST_DIR`) |
| JWT Algorithm | HS256 vs RS256 | HS256 (simpler for assignment; document trade-off) |
| Checkpoint DB | Same as app DB vs Separate | Separate `./data/checkpoints.sqlite` |
| Graph Visualization | Mermaid PNG vs SVG | PNG (caching easier) |
| Pricing Table Format | JSON env var vs YAML file | JSON in `MODEL_PRICING` env var |

---

## File Structure Summary (Workflow-Centric)

```
src/
├── config.py                 # 12-factor config
├── main.py                   # FastAPI app + lifespan
├── database.py               # SQLAlchemy async engine
├── models/                   # Shared SQLAlchemy models
│   ├── project.py
│   ├── document.py
│   ├── pattern.py
│   ├── run.py
│   ├── task.py
│   ├── usage.py
│   └── audit.py
├── auth/                     # Shared JWT auth
│   ├── jwt_handler.py
│   └── dependencies.py
├── storage/
│   └── file_store.py         # FileStore abstraction
├── vectorstore/
│   └── chroma_client.py      # ChromaDB client
├── schemas/                  # Shared Pydantic request/response
│   ├── hitl.py
│   ├── project.py
│   ├── document.py
│   ├── pattern.py
│   ├── run.py
│   └── task.py
├── middleware/
│   ├── auth.py
│   ├── idempotency.py
│   └── audit.py
├── exceptions.py             # Structured error handling
├── seeds/
│   └── patterns.yaml         # 10+ canonical patterns
│
├── workflows/
│   ├── __init__.py
│   ├── checkpointer.py       # Shared SQLite checkpointer
│   ├── hooks.py              # Shared pre/post/error hooks
│   │
│   ├── requirements/         # ===== WORKFLOW 1 =====
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── nodes.py
│   │   ├── graph.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── document_ingestor.py
│   │   │   ├── gap_analyzer.py
│   │   │   ├── clarification_generator.py
│   │   │   ├── requirements_synthesizer.py
│   │   │   └── validator.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   └── rag_service.py          # Workflow-specific RAG
│   │   └── routers/
│   │       ├── __init__.py
│   │       └── requirements.py         # POST /workflows/requirements
│   │
│   ├── planning/             # ===== WORKFLOW 2 =====
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── graph.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── pattern_selector.py
│   │   │   ├── researcher.py
│   │   │   ├── architect.py
│   │   │   ├── planner.py
│   │   │   └── critic.py
│   │   ├── subgraphs/
│   │   │   ├── __init__.py
│   │   │   ├── researcher.py           # Parallel RAG + web search
│   │   │   └── planner_critic.py       # Evaluator-Optimizer cycle
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   └── router.py               # Complexity-based routing
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── pattern_service.py      # Workflow-specific KB queries
│   │   │   └── research_service.py
│   │   └── routers/
│   │       ├── __init__.py
│   │       └── planning.py             # POST /workflows/planning
│   │
│   └── codegen/              # ===== WORKFLOW 3 =====
│       ├── __init__.py
│       ├── state.py
│       ├── graph.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── developer.py
│       │   └── reviewers.py            # workflow/prompt/security reviewers
│       ├── subgraph_builder.py         # Dynamic per-task subgraph
│       ├── services/
│       │   ├── __init__.py
│       │   └── workspace_service.py    # File workspace management
│       └── routers/
│           ├── __init__.py
│           └── codegen.py              # POST /workflows/codegen
│
├── routers/                  # Shared top-level routers
│   ├── __init__.py
│   ├── health.py
│   ├── projects.py
│   ├── documents.py
│   ├── patterns.py
│   ├── runs.py                 # GET status, SSE, resume, approve/reject
│   ├── tasks.py                # Task CRUD (planning phase)
│   ├── traceability.py
│   ├── audit.py
│   └── workflows.py            # GET /workflows/{name}/graph.png
│
└── websockets/
    ├── __init__.py
    └── hitl.py                 # WebSocket HITL handler (shared)
```

**Key principle:** Each workflow (`requirements/`, `planning/`, `codegen/`) is a self-contained package with its own `agents/`, `services/`, `routers/`, `subgraphs/`, `nodes/`. Shared infrastructure stays at the top level.

---

## Verification Checklist Per Phase

| Phase | Must Pass |
|-------|-----------|
| M1 | Auth works, project CRUD, upload→parse→embed, health check, Swagger green |
| M2 | Pattern CRUD, search returns relevant results, 10 seeds loaded |
| M3 | Requirements workflow: trigger → clarify (WS) → approve → artifact; resume works |
| M4 | Planning workflow: trigger → pattern select → research → architecture → tasks → validate → approve; task editing works |
| M5 | Codegen workflow: trigger → sequential tasks → parallel reviewers → retry → bundle → approve → download |
| M6 | All workflows: checkpoint resume, SSE replay, WS hardening, hooks emit events, cost ceilings, graph PNGs |
| M7 | Usage breakdown, traceability map, research citations, audit log, full E2E test passes |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| LangGraph checkpoint serialization issues | Test early with complex state; use Pydantic models in state |
| WebSocket reconnection complexity | Build idempotency from day 1 (request_id from checkpoint) |
| Multi-source research hallucination | Strict citation enforcement; validator checks citation format |
| Pattern over-selection | Pattern Selector has explicit "minimal set" instruction + critic validation |
| Cost ceiling mid-run | Check before each LLM call; fail fast with clear error |
| Cross-project data leakage | Enforce project_id filter in ALL ChromaDB queries and SQL queries |

---

## Success Criteria

1. **All 3 workflows run end-to-end** with a sample BRD
2. **All mandatory concepts demonstrated** and documented in README
3. **80% test coverage** on changed files
4. **Swagger always green**; structured error envelopes
5. **Resumability verified** by killing/restarting mid-run
6. **HITL works over WebSocket** with reconnection handling
7. **Traceability query** shows doc→req→pattern→task→file chain
8. **README has curl examples** for complete pipeline