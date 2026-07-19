# Agent Runtime Control Operations

## Purpose

The Agent route uses Redis as the cross-worker authority for admission control.
It protects one shared OpenAI provider key while preserving the existing local
`asyncio.Semaphore`, database idempotency records, and provider circuit breaker.

## Request Flow

1. Validate the Agent input and create an anonymous cart session when needed.
2. Claim the existing database idempotency record.
3. Apply the Redis fixed-window rate limit.
4. Wait for one Redis global workflow lease for at most 10 seconds.
5. Apply the existing process-local semaphore and execute `Runner.run`.
6. Persist the Agent response through the existing idempotency completion path.

The global lease wait is outside `OPENAI_AGENT_TIMEOUT_SECONDS`. The 15-second
execution budget covers local queueing, provider execution, and the bounded retry
after a global slot has been acquired.

## Global and Local Limits

| Control | Authority | Default | Failure behavior |
| --- | --- | --- | --- |
| Redis workflow lease | All backend workers | 3 concurrent workflows | Wait 10 seconds, then `429 AGENT_OPENAI_BUSY` with `Retry-After: 2`. |
| Local `asyncio.Semaphore` | One backend process | 3 concurrent workflows | Supplemental guard inside a worker. |
| Authenticated fixed window | Redis | 30 requests/minute | `429 AGENT_RATE_LIMITED`. |
| Anonymous cart fixed window | Redis | 20 requests/minute | `429 AGENT_RATE_LIMITED`. |

Every Redis lease has an owner token and a TTL of at least 45 seconds. Release
deletes a lease only when the owner token still matches. If a process dies before
release, the TTL recovers the slot. Redis control failures are fail-closed only for
the Agent route and return `503 AGENT_CAPACITY_UNAVAILABLE`.

IP-level throttling is intentionally deferred. Caddy/proxy trusted-client-IP policy
must be decided first; using an untrusted forwarded header would make an IP limit
both unreliable and easy to bypass.

## Environment Values

```dotenv
OPENAI_AGENT_MAX_CONCURRENCY=3
OPENAI_AGENT_QUEUE_TIMEOUT_SECONDS=10
OPENAI_AGENT_BUSY_RETRY_AFTER_SECONDS=2
OPENAI_AGENT_GLOBAL_LEASE_TTL_SECONDS=45
OPENAI_AGENT_AUTHENTICATED_RATE_LIMIT_PER_MINUTE=30
OPENAI_AGENT_ANONYMOUS_RATE_LIMIT_PER_MINUTE=20
OPENAI_AGENT_TIMEOUT_SECONDS=15
AGENT_RELEASE=local
```

Use `.env.example` as the safe template. Do not commit a real `OPENAI_API_KEY` or a
deployment-specific release identifier.

## Observability

The backend emits `agent_request_completed` with these structured fields:

```text
agent_total_ms
agent_idempotency_ms
agent_rate_limit_ms
agent_global_slot_wait_ms
agent_global_slot_acquire_ms
agent_llm_workflow_ms
agent_tool_execution_ms
agent_response_persist_ms
agent_outcome
agent_rate_limited
agent_global_slot_acquired
agent_global_slot_rejected
```

The existing OpenAI Agents trace receives only safe correlation metadata:

```text
request_id
conversation_id
environment
route
authenticated
agent_release
```

OpenAI traces explain model and tool workflow time. Backend structured logs explain
request admission, Redis queueing, database idempotency, and response persistence.
Neither trace metadata nor Redis keys contain raw chat messages, email addresses,
order details, shipping details, tokens, or raw user identifiers.

## Frontend Idempotency Check

`apps/frontend/src/components/AgentFloatingButton.tsx` already creates a fresh
UUID-based idempotency key for a new submission and reuses it only for a retryable
network failure. `apps/frontend/src/lib/api.ts` attaches that header only to the
Agent chat request. No frontend request shape change is required for this work.

