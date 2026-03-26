# SpeakX Journey Notification Engine

AI-powered notification pipeline that generates personalized Hinglish push notifications based on each user's behavioral state and journey context. Built as a modular monolith deployed via Docker Compose on a single VPS.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Admin API (FastAPI)                       │
│  /admin/ingest  /admin/config  /admin/health  /admin/shadow     │
└──────┬──────────────────┬────────────────────────────┬──────────┘
       │                  │                            │
       ▼                  ▼                            ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐
│  Ingestion   │  │   Config     │  │  Notification Pipeline   │
│  CSV → LLM   │  │  Manager     │  │                          │
│  → DB Store  │  │  (DB-backed) │  │  Strategy → Prompt Build │
└──────────────┘  └──────────────┘  │  → LLM Gen → Frequency  │
                                    │  → CleverTap Delivery    │
┌──────────────┐  ┌──────────────┐  └──────────────────────────┘
│ Redis Streams│  │ State Engine │         │
│  Consumer    │──│ 12-state FSM │         │
│  (Events)    │  │ + Evaluator  │         │
└──────────────┘  └──────────────┘         ▼
                                    ┌──────────────────┐
┌──────────────┐                    │    Analytics      │
│ Celery Beat  │                    │ CleverTap Sync    │
│ 9 schedules  │                    │ Attribution       │
│ temporal scan│                    │ Daily Snapshots   │
└──────────────┘                    └──────────────────┘
```

### Modules

| Module | Directory | Purpose |
|--------|-----------|---------|
| Ingestion | `app/ingestion/` | CSV parsing, validation, hierarchy building, LLM analysis |
| State Engine | `app/state_engine/` | 12-state behavioral FSM, metric evaluation, temporal scans |
| Notifications | `app/notifications/` | Three-layer segmented generation, frequency cap, delivery |
| Events | `app/events/` | Redis Streams consumer, event processing, routing |
| Analytics | `app/analytics/` | CleverTap sync, attribution, daily snapshots, tracking |
| LLM | `app/llm/` | Claude Sonnet provider, prompt schemas |
| Config | `app/config/` | Database-backed runtime configuration |
| API | `app/api/` | Admin endpoints, health check, dependencies |
| Workers | `workers/` | Celery tasks, event consumer, ingestion worker |

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Anthropic API key (Claude Sonnet)
- CleverTap account credentials

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — fill in ANTHROPIC_API_KEY, CLEVERTAP_ACCOUNT_ID, CLEVERTAP_PASSCODE, SECRET_KEY

# 2. Start all services
docker compose up --build

# 3. Verify health
curl http://localhost:8000/admin/health

# 4. Run database migrations
docker compose exec app alembic upgrade head

# 5. Ingest a journey CSV
curl -X POST http://localhost:8000/admin/ingest \
  -H "X-API-Key: $SECRET_KEY" \
  -F "file=@journey.csv"
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL async connection string | Yes |
| `REDIS_URL` | Redis connection URL | Yes |
| `ANTHROPIC_API_KEY` | Claude API key for LLM generation | Yes |
| `CLEVERTAP_ACCOUNT_ID` | CleverTap account ID | Yes |
| `CLEVERTAP_PASSCODE` | CleverTap API passcode | Yes |
| `SECRET_KEY` | Admin API authentication key | Yes |
| `ENVIRONMENT` | `development` or `production` | No (default: development) |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | No (default: INFO) |

## Services

| Service | Port | Purpose |
|---------|------|---------|
| `app` | 8000 | FastAPI application server |
| `worker` | — | Celery worker (default, notifications, ingestion queues) |
| `beat` | — | Celery Beat scheduler (9 periodic tasks) |
| `consumer` | — | Redis Streams event consumer |
| `postgres` | 5432 | PostgreSQL 15 database |
| `redis` | 6379 | Redis 7 (broker, streams, cache) |
| `flower` | 5555 | Celery task monitoring dashboard |
| `metabase` | 3000 | Analytics dashboard (SQL queries in `docs/metabase-queries.md`) |

## Admin API

All endpoints require `X-API-Key` header (except health check).

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/admin/health` | Service health check (PostgreSQL, Redis, Celery) |
| `POST` | `/admin/ingest` | Upload journey CSV for async ingestion |
| `GET` | `/admin/ingest/{journey_id}/status` | Check ingestion progress |
| `GET` | `/admin/config` | List all configuration entries |
| `PUT` | `/admin/config/{key}` | Update a configuration value |
| `GET` | `/admin/notifications/shadow-review` | Review shadow-mode notifications |

See `docs/api.md` for detailed request/response schemas and examples.

## Configuration

All runtime-tunable parameters are stored in the `app_config` database table, not environment variables. Default values are seeded from `config/defaults.yaml` on application startup.

Update configuration via the admin API:

```bash
# Get all config entries
curl -H "X-API-Key: $SECRET_KEY" http://localhost:8000/admin/config

# Get entries by category
curl -H "X-API-Key: $SECRET_KEY" "http://localhost:8000/admin/config?category=dormancy"

# Update a config value
curl -X PUT -H "X-API-Key: $SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"value": 72}' \
  http://localhost:8000/admin/config/dormancy.threshold_hours
```

## Notification Pipeline

The notification system uses **three-layer segmentation**:

1. **State Layer** — User's behavioral state (12 states: new_unstarted, onboarding, progressing, struggling, bored, mastering, chapter_transitioning, dormant_short, dormant_long, churned, completing, completed)
2. **Theme Layer** — Notification theme matched to state (motivational, progress, story_hook, challenge, reminder, celebration, curiosity, urgency)
3. **Slot Layer** — Time-of-day optimization (5 daily slots + 1 event-triggered)

### Shadow Mode

The system starts in shadow mode by default. Notifications are generated and stored but not delivered to CleverTap. Review shadow notifications via:

```bash
curl -H "X-API-Key: $SECRET_KEY" \
  "http://localhost:8000/admin/notifications/shadow-review?limit=50&state=struggling"
```

Switch to live mode by updating the config:

```bash
curl -X PUT -H "X-API-Key: $SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"value": "live"}' \
  http://localhost:8000/admin/config/notification.mode
```

See `docs/go-live-checklist.md` for the full go-live procedure.

## Monitoring

- **Metabase** (port 3000) — Analytics dashboard with pre-built SQL queries (`docs/metabase-queries.md`)
- **Flower** (port 5555) — Celery task monitoring
- **Health endpoint** — `GET /admin/health` returns PostgreSQL, Redis, and Celery worker status
- **Structured logs** — JSON-formatted via structlog with request ID correlation

## Testing

```bash
# Run full test suite
docker compose exec app pytest tests/ -v

# Run specific test categories
docker compose exec app pytest tests/test_state_machine.py -v     # 12-state FSM
docker compose exec app pytest tests/test_llm_output.py -v        # LLM generation + fallback
docker compose exec app pytest tests/test_frequency_cap.py -v     # Send limits
docker compose exec app pytest tests/test_clevertap.py -v         # Delivery + retry
docker compose exec app pytest tests/test_ingestion.py -v         # CSV pipeline
docker compose exec app pytest tests/test_temporal.py -v          # Dormancy + transitions
docker compose exec app pytest tests/test_edge_cases.py -v        # Boundary conditions
docker compose exec app pytest tests/test_health.py -v            # Health endpoint

# Lint check
docker compose exec app ruff check app/ workers/ tests/
```

**57 tests** covering: state machine transitions, LLM output validation, frequency capping, CleverTap delivery, CSV ingestion, temporal scans, and edge cases.

## Folder Structure

```
speakx-notification-engine/
├── app/
│   ├── analytics/          # CleverTap sync, attribution, snapshots, tracking
│   ├── api/                # FastAPI endpoints, dependencies, routing
│   ├── config/             # Settings, DB-backed config manager
│   ├── events/             # Redis Streams consumer, event processor, schemas
│   ├── ingestion/          # CSV parser, validator, ingestion service, schemas
│   ├── llm/                # Claude provider, prompt schemas
│   ├── models/             # SQLAlchemy models (journey, user, notification, config, analytics)
│   ├── notifications/      # Strategy, prompt builder, generator, frequency, delivery, scheduler
│   ├── state_engine/       # 12-state machine, evaluator, transitions, temporal scans
│   └── main.py             # FastAPI application factory
├── workers/
│   ├── celery_app.py       # Celery configuration + beat schedule
│   ├── temporal_worker.py  # Dormancy/transition scan + analytics tasks
│   ├── notification_worker.py  # Notification generation tasks
│   ├── ingestion_worker.py # Async CSV ingestion task
│   └── event_consumer.py   # Redis Streams consumer entry point
├── alembic/                # Database migrations
├── config/
│   └── defaults.yaml       # Default configuration values
├── templates/
│   ├── notification_examples.json  # LLM few-shot examples
│   └── fallback_notifications.json # Fallback notification templates (~60)
├── tests/                  # Pytest test suite (57 tests)
├── scripts/
│   └── load_test.py        # Redis Stream load test script
├── docs/
│   ├── api.md              # Detailed API documentation
│   ├── metabase-queries.md # Dashboard SQL queries
│   └── go-live-checklist.md # Shadow-to-live procedure
├── docker-compose.yml      # 8-service deployment
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## Known Limitations

- **Single VPS deployment** — not designed for multi-server/Kubernetes (V2)
- **Hinglish only** — no multi-language support beyond English-Hindi mix (V2)
- **No A/B testing** — notification variants not tested against each other (V2)
- **No real-time CleverTap webhooks** — uses polling every 30 minutes (V2)
- **In-memory rate limiter** — resets on restart (acceptable for admin API)
- **No frontend UI** — admin uses API + Metabase dashboard
