# Agent Runtime API Contract

## Scope

This document defines the runtime admission contract for `POST /api/agent/chat`.
It does not change the chat request body, the Agent tool list, prompts, search, or
recommendation scoring.

## Idempotency

- The client sends `Idempotency-Key` only for `POST /api/agent/chat`.
- A new user submission generates a new UUID-based key, even when the message text
  is identical to an earlier submission.
- A network retry of the same submission reuses its original key.
- The server keeps the existing database-backed idempotency behavior:
  completed requests replay their stored response and a still-running request is
  not executed a second time.
- No `client_request_id` field is added to the request body.

## Admission Responses

| Condition | HTTP | `error.code` | Client behavior |
| --- | --- | --- | --- |
| Per-minute Agent limit exceeded | `429` | `AGENT_RATE_LIMITED` | Wait for `Retry-After` before allowing another attempt. |
| Global OpenAI workflow slots are busy for the full queue window | `429` | `AGENT_OPENAI_BUSY` | Respect `Retry-After: 2`; the original request was not sent to the model. |
| Redis admission control is unavailable | `503` | `AGENT_CAPACITY_UNAVAILABLE` | Show a temporary availability error. Do not assume an Agent workflow ran. |

The rate limits are fixed windows per minute:

- Authenticated user: 30 requests per minute.
- Anonymous cart session: 20 requests per minute.

Raw user IDs, messages, emails, orders, and shipping data are not used as Redis key
material. Actor identifiers are one-way hashed before key construction.

## Retry Guidance

`Retry-After` is part of the HTTP response for admission rejections. A UI may offer
a retry after that period, but it must create a new idempotency key unless it is
retrying the same network-failed submission.

