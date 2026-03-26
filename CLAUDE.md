# CLAUDE.md — SpeakX Journey Notification Engine

**Version:** V1
**Date:** 2026-03-09
**Python:** 3.11+

## Project Summary

AI-powered notification pipeline for SpeakX English learning app. Ingests journey CSVs, tracks user behavior through a 12-state machine, generates personalized Hinglish push notifications via Claude Sonnet, and delivers through CleverTap. Deployed as a modular monolith via Docker Compose.

## Tech Stack

- **Framework:** FastAPI (async, App Router)
- **ORM:** SQLAlchemy 2.0 async (`AsyncSession`)
- **Database:** PostgreSQL 15 (via asyncpg) with generic `JSON` column type (not JSONB — for SQLite test compatibility)
- **Cache/Broker:** Redis 7 (Celery broker + Redis Streams for events)
- **Task Queue:** Celery 5.3+ with Beat scheduler (9 periodic tasks)
- **LLM:** Anthropic Claude Sonnet 4.6 via `anthropic` SDK
- **State Machine:** python-statemachine 2.1+ (`start_value` expects string, use `current_state_value`)
- **Delivery:** CleverTap Push Notification API via httpx async
- **Logging:** structlog (JSON in production, console in dev)
- **Validation:** Pydantic v2
- **Linting:** ruff

## File Structure

```
app/
├── analytics/          # CleverTap sync, attribution, snapshots, tracking
├── api/                # Admin endpoints (admin.py), health check, deps (rate limiter, auth)
├── config/             # settings.py (Pydantic settings), manager.py (DB-backed config)
├── events/             # Redis Streams consumer, event processor, schemas
├── ingestion/          # CSV parser, validator, service, schemas
├── llm/                # Claude provider, prompt/copy schemas
├── models/             # SQLAlchemy models: journey, user, notification, config, analytics
├── notifications/      # Strategy, prompt_builder, generator, frequency, delivery, scheduler
├── state_engine/       # machine.py (12-state FSM), evaluator, transitions, temporal scans
└── main.py             # FastAPI factory (structlog, middleware, lifespan)

workers/
├── celery_app.py       # Celery config + beat schedule (9 tasks)
├── temporal_worker.py  # Dormancy + chapter scan + CleverTap sync + snapshots
├── notification_worker.py  # Notification slot + event-triggered tasks
├── ingestion_worker.py # Async CSV ingestion task
└── event_consumer.py   # Redis Streams consumer entry point

config/defaults.yaml    # Default config values seeded on startup
templates/              # LLM few-shot examples + fallback notification templates
tests/                  # 57 tests across 8 test files
docs/                   # API docs, Metabase queries, go-live checklist
```

## Key Architectural Decisions

1. **Modular monolith** — All modules in one process, communicate through interfaces. No microservices.
2. **Shadow mode** — Notifications are generated but not delivered until admin switches to live mode.
3. **Database-backed config** — All tunable parameters in `app_config` table, NOT environment variables. Seeded from `config/defaults.yaml`.
4. **Generic JSON columns** — Using SQLAlchemy `JSON` (not PostgreSQL `JSONB`) for SQLite test compatibility.
5. **Three-layer notification segmentation** — State × Theme × Slot for personalized generation.
6. **Redis Streams** — Consumer group pattern (XREADGROUP/XACK) for reliable event delivery.

## The 12 States

```
new_unstarted → onboarding → progressing_active
                                ├── progressing_slow (deceleration)
                                ├── struggling → progressing_active (recovery)
                                ├── bored_skimming → progressing_active (re-engagement)
                                ├── chapter_transition → progressing_active
                                ├── completing → completed
                                ├── dormant_short → dormant_long → churned
                                └── (reactivation from any dormant/churned → progressing_active)
```

All 12 states: `new_unstarted`, `onboarding`, `progressing_active`, `progressing_slow`, `struggling`, `bored_skimming`, `chapter_transition`, `dormant_short`, `dormant_long`, `churned`, `completing`, `completed`.

## Module Communication Rules

- Modules communicate through public interfaces only
- No cross-module internal imports (e.g., notifications should not import state engine internals)
- Events flow: Redis Streams → Consumer → Processor → State Engine → (async) Notification Worker
- Config access always through `ConfigManager`, never direct DB queries

## Testing

```bash
# Full suite (57 tests)
docker compose exec app pytest tests/ -v

# Lint
docker compose exec app ruff check app/ workers/ tests/
```

Test categories: state machine (19), ingestion (8), LLM output (5), frequency cap (5), CleverTap (4), temporal (5), edge cases (11), health (1).

## Environment Setup

```bash
cp .env.example .env
# Fill: ANTHROPIC_API_KEY, CLEVERTAP_ACCOUNT_ID, CLEVERTAP_PASSCODE, SECRET_KEY
docker compose up --build
docker compose exec app alembic upgrade head
```

**Note on macOS:** Docker path may require `export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"`.

## Important Notes

- `NotificationPrompt.chapter_analysis` is typed as `dict` (not `ChapterAnalysis` Pydantic model) for compatibility
- `python-statemachine` v2: use `start_value` (string), access state via `current_state_value`
- CleverTap delivery handles non-JSON 200 responses gracefully (try/except fallback)
- CSV parser enforces: 50 MB size limit, 100K row limit, 10K cell char limit, encoding fallback chain
- Redis consumer: exponential backoff reconnection (max 5 attempts), malformed messages always ACK'd
- Frequency cap: 6 notifications/day, suppresses if user was active within 120 minutes
- Celery Beat runs in IST timezone (Asia/Kolkata)

## Configurable Parameters

All in `app_config` table. Categories: `dormancy`, `frequency`, `timing`, `behavioral`, `llm`, `shadow`, `attribution`. See `config/defaults.yaml` for the full list with descriptions.

Key parameters:
- `dormancy.short_threshold_days` = 2
- `dormancy.long_threshold_days` = 7
- `dormancy.churned_threshold_days` = 30
- `frequency.max_per_day` = 6
- `frequency.suppress_if_active_minutes` = 120
- `behavioral.struggling_avg_score_threshold` = 60
- `behavioral.onboarding_completion_threshold` = 3
- `shadow.enabled` = true
- `attribution.window_hours` = 4
