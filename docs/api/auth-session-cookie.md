# Authentication Session Cookie Policy

## Decision

뭐바를래 MVP 인증은 **서버 세션 + HttpOnly cookie** 방식으로 통일한다.

프론트엔드는 access token / refresh token을 직접 저장하지 않는다. 백엔드는 로그인 성공 시 세션 토큰을 `HttpOnly` 쿠키로 발급하고, 이후 보호 API는 쿠키에 담긴 세션 토큰으로 현재 사용자를 식별한다.

## Why This Direction

현재 서비스 목표는 모바일 앱이나 외부 공개 API가 아니라 **웹 자사몰 고도화**다. 이 범위에서는 프론트가 토큰 저장, refresh 재시도, 만료 복구, 로그아웃 동기화를 직접 관리하는 방식보다 백엔드가 세션을 통제하는 방식이 더 안정적이다.

이 방식은 다음 목표에 맞다.

- 로그인 유지 UX를 단순하게 만든다.
- 프론트가 인증 토큰을 JavaScript 저장소에 두지 않는다.
- 로그아웃, 비밀번호 재설정 후 전체 세션 만료, 강제 로그아웃이 쉽다.
- 이메일 로그인과 소셜 로그인 모두 최종적으로 같은 세션 발급 흐름을 사용한다.
- 서버가 여러 대가 되어도 공통 세션 저장소를 사용하면 sticky session에 의존하지 않는다.

## Alternatives Considered

### Bearer JWT stored by frontend

프론트가 `access_token`, `refresh_token`을 저장하고 매 요청마다 `Authorization: Bearer`를 붙이는 방식이다.

- 장점: 모바일 앱/외부 API 확장에 자연스럽고 access token 검증은 빠르다.
- 단점: 프론트가 토큰 저장, 만료, refresh, 재시도, 로그아웃 동기화를 모두 책임져야 한다. 토큰 저장 위치를 잘못 잡으면 XSS에 취약하다.

### Access token in memory + refresh token HttpOnly cookie

refresh token은 쿠키에 두고, access token은 프론트 메모리에만 두는 방식이다.

- 장점: localStorage 저장보다 안전하고 API 스타일을 유지할 수 있다.
- 단점: 앱 시작 시 refresh, 동시 401 처리, access token 재발급 race 처리 등 프론트 auth client가 필요하다.

### JWT in HttpOnly cookie

JWT 자체를 쿠키에 담는 방식이다.

- 장점: 프론트 구현이 단순하고 서버 조회를 줄일 수 있다.
- 단점: 즉시 폐기, 강제 로그아웃, 비밀번호 재설정 후 전체 세션 만료가 까다롭다. 결국 blacklist나 token version 같은 서버 상태가 필요해질 수 있다.

## Final Contract

### Cookie

- Cookie name: `mwbl_session`
- Token type: random opaque token
- Stored in browser as `HttpOnly` cookie
- Stored in DB only as hash
- `SameSite=Lax`
- `Secure=false` for local HTTP development
- `Secure=true` for deployed HTTPS environments
- `Path=/`
- Default TTL: 14 days

### Backend session store

초기 구현은 PostgreSQL `auth_sessions` 테이블을 사용한다.

Required fields:

- `id`
- `user_id`
- `token_hash`
- `expires_at`
- `revoked_at`
- `last_used_at`
- `created_at`
- optional `user_agent`
- optional `ip_address`

Traffic이 커져 세션 조회가 병목이 되면 Redis session store로 이전할 수 있다. 이때도 브라우저와 API 계약은 유지한다.

### Frontend rules

- 인증 토큰을 `localStorage` 또는 `sessionStorage`에 저장하지 않는다.
- `Authorization: Bearer ...` 헤더를 직접 만들지 않는다.
- 인증이 필요한 요청은 `fetch(..., { credentials: "include" })`를 사용한다.
- 앱 시작 시 `/api/me`를 호출해 로그인 상태를 확인한다.
- 로그아웃은 `POST /api/auth/logout`을 호출하고, 성공하면 프론트 auth state를 비운다.

### Backend rules

- 로그인, 회원가입, Google 로그인 성공 시 `Set-Cookie: mwbl_session=...`을 내려준다.
- 보호 API는 `Authorization` 헤더가 아니라 `mwbl_session` 쿠키로 현재 사용자를 판단한다.
- 로그아웃 시 현재 세션을 revoke하고 쿠키를 삭제한다.
- 비밀번호 재설정 성공 시 해당 사용자의 모든 활성 세션을 revoke한다.
- Google-only 계정에는 비밀번호 재설정 코드를 발송하지 않는다.
- 모바일 앱/외부 API가 필요해지면 별도 Bearer token 인증을 추가 검토한다.

## API Contract Summary

### `POST /api/auth/signup`

Request body keeps the existing signup shape.

Response:

```json
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "nickname": "nickname",
    "role": "USER",
    "status": "ACTIVE",
    "created_at": "2026-07-04T00:00:00Z"
  }
}
```

Also sets `mwbl_session` cookie.

### `POST /api/auth/login`

Response body is the same user wrapper as signup. Also sets `mwbl_session` cookie.

Email login failures return `401` with a specific code so the login screen can guide the user:

| Code | Meaning |
|---|---|
| `ACCOUNT_NOT_FOUND` | No user is registered with the email. |
| `INVALID_PASSWORD` | The email account exists but the password does not match. |
| `EMAIL_LOGIN_NOT_AVAILABLE` | The email belongs to a social-login-only account. |
| `USER_NOT_ACTIVE` | The account exists but is not active. |

This detailed contract intentionally favors login UX. Password-reset requests still return the same
message regardless of account existence.

### `DELETE /api/me`

Requires an authenticated session. The endpoint soft-deletes the account and expires the session cookie.

- The user row and order/payment/claim/consent history are retained.
- Email, nickname, phone, login providers, sessions, saved addresses, wishlist, recent views, skin data,
  and personalized preference profiles are removed or anonymized.
- Reviews, event logs, and agent tool records are retained without the user association.
- The original email and nickname can be used for a new signup after deletion.
- Admin accounts return `403 ADMIN_ACCOUNT_DELETION_NOT_ALLOWED`.

Response:

```json
{
  "message": "회원탈퇴가 완료되었습니다."
}
```

### `POST /api/auth/google`

Google token verification and account linking stay the same. Successful login sets the same `mwbl_session` cookie.

### `GET /api/me`

Reads `mwbl_session` cookie. Returns current user or `401 INVALID_SESSION`.

### `POST /api/auth/logout`

Reads `mwbl_session` cookie, revokes that session, deletes the cookie, and returns a message.

### `POST /api/auth/refresh`

No refresh token body is used. If kept, this endpoint reads `mwbl_session`, rotates or extends the current server session, and re-sets the cookie.

### `POST /api/auth/password-reset`

The response must not reveal whether the email exists. A reset code is only issued if the email belongs to an email/password account.

### `POST /api/auth/password-reset/confirm`

On successful password change, all active sessions for the user are revoked.

## Scaling Note

Do not store sessions in backend process memory.

Allowed:

- PostgreSQL `auth_sessions`
- Redis session store

Avoid:

- per-process memory session
- load balancer sticky session as the only way to keep login state

With a shared session store, multiple backend instances behind a load balancer can validate the same session cookie.
