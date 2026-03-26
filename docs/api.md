# Admin API Documentation

Base URL: `http://localhost:8000`

All endpoints under `/admin/` require the `X-API-Key` header (except the health check). Rate limited to 60 requests per minute per IP.

---

## 1. Health Check

**`GET /admin/health`**

Returns the status of all backend services.

### Authentication

None required.

### Response

```json
{
  "status": "healthy",
  "timestamp": "2026-03-09T14:30:00+00:00",
  "environment": "development",
  "services": {
    "postgres": {
      "status": "up",
      "latency_ms": 2.3
    },
    "redis": {
      "status": "up",
      "latency_ms": 1.1
    },
    "celery_workers": {
      "status": "up",
      "active_workers": 1
    }
  }
}
```

**Status values:** `healthy` (all up), `degraded` (Redis or Celery down), `unhealthy` (PostgreSQL down).

### Example

```bash
curl http://localhost:8000/admin/health
```

---

## 2. Trigger Ingestion

**`POST /admin/ingest`**

Upload a journey CSV file for asynchronous ingestion. The file is queued for processing via Celery.

### Authentication

`X-API-Key` header required.

### Request

Multipart form upload with a single `file` field. Only `.csv` files accepted.

### Response

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued",
  "message": "Ingestion started"
}
```

### Errors

| Status | Detail |
|--------|--------|
| 400 | `Only CSV files are accepted` |
| 403 | `Invalid or missing API key` |
| 429 | `Rate limit exceeded` |

### Example

```bash
curl -X POST http://localhost:8000/admin/ingest \
  -H "X-API-Key: your-secret-key" \
  -F "file=@journey.csv"
```

---

## 3. Ingestion Status

**`GET /admin/ingest/{journey_id}/status`**

Check the progress of a journey ingestion task.

### Authentication

`X-API-Key` header required.

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `journey_id` | string (UUID) | Journey ID returned from ingestion |

### Response

```json
{
  "journey_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "active",
  "total_chapters": 12
}
```

**Status values:** `analyzing` (in progress), `active` (complete), `failed`.

### Errors

| Status | Detail |
|--------|--------|
| 403 | `Invalid or missing API key` |
| 404 | `Journey not found` |
| 429 | `Rate limit exceeded` |

### Example

```bash
curl -H "X-API-Key: your-secret-key" \
  http://localhost:8000/admin/ingest/a1b2c3d4-e5f6-7890-abcd-ef1234567890/status
```

---

## 4. List Configuration

**`GET /admin/config`**

List all runtime configuration entries, optionally filtered by category.

### Authentication

`X-API-Key` header required.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category` | string | No | Filter by category (e.g., `dormancy`, `notification`, `frequency`) |

### Response

```json
[
  {
    "key": "dormancy.threshold_hours",
    "value": 48,
    "description": "Hours of inactivity before marking user as dormant_short",
    "category": "dormancy",
    "updated_at": "2026-03-09 14:30:00"
  },
  {
    "key": "notification.mode",
    "value": "shadow",
    "description": "Notification delivery mode: shadow or live",
    "category": "notification",
    "updated_at": ""
  }
]
```

### Errors

| Status | Detail |
|--------|--------|
| 403 | `Invalid or missing API key` |
| 429 | `Rate limit exceeded` |

### Example

```bash
# All config entries
curl -H "X-API-Key: your-secret-key" \
  http://localhost:8000/admin/config

# Filtered by category
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/admin/config?category=dormancy"
```

---

## 5. Update Configuration

**`PUT /admin/config/{key}`**

Update a single configuration value. Creates the entry if it does not exist.

### Authentication

`X-API-Key` header required.

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `key` | string | Configuration key (e.g., `dormancy.threshold_hours`) |

### Request Body

```json
{
  "value": 72
}
```

The `value` field accepts any JSON-serializable type (string, number, boolean, object, array).

### Response

```json
{
  "key": "dormancy.threshold_hours",
  "value": 72,
  "updated_by": "admin",
  "status": "updated"
}
```

### Errors

| Status | Detail |
|--------|--------|
| 403 | `Invalid or missing API key` |
| 422 | Validation error (invalid request body) |
| 429 | `Rate limit exceeded` |

### Example

```bash
curl -X PUT http://localhost:8000/admin/config/dormancy.threshold_hours \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"value": 72}'
```

---

## 6. Shadow Notification Review

**`GET /admin/notifications/shadow-review`**

List shadow-mode notifications for review before going live. Includes user context and journey information.

### Authentication

`X-API-Key` header required.

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | 50 | Number of results (1-200) |
| `offset` | integer | No | 0 | Pagination offset |
| `state` | string | No | — | Filter by user state at generation |
| `theme` | string | No | — | Filter by notification theme |

### Response

```json
[
  {
    "notification_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "user_id": "user_12345",
    "state_at_generation": "struggling",
    "theme": "motivational",
    "title": "Ruk mat, champion! 💪",
    "body": "Tera Chapter 3 ka adventure abhi baaki hai. Aaj ka ek lesson tera confidence badha dega!",
    "cta": "Abhi shuru karo →",
    "generation_method": "llm",
    "created_at": "2026-03-09T14:30:00+00:00",
    "learning_reason": "career growth",
    "journey_name": "English for Professionals"
  }
]
```

### Errors

| Status | Detail |
|--------|--------|
| 403 | `Invalid or missing API key` |
| 422 | Validation error (limit out of range) |
| 429 | `Rate limit exceeded` |

### Example

```bash
# All shadow notifications
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/admin/notifications/shadow-review?limit=50"

# Filtered by state and theme
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/admin/notifications/shadow-review?state=struggling&theme=motivational&limit=20"
```
