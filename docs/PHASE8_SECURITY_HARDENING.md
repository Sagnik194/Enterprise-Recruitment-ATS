# Phase 8 security hardening — implementation status and integration guide

This document preserves the useful technical material from the former root `README.md`. That file described a proposed Phase 8 hardening package and gave integration snippets. Those snippets must not be mistaken for proof that the controls are active in the current ATS.

## 1. Verified current state

The following points were checked against the current repository source:

| Area | Current implementation observed |
|---|---|
| Browser sessions | `SessionMiddleware` is registered in `app/main.py`; it uses `SESSION_SECRET_KEY` when configured and otherwise falls back to `JWT_SECRET_KEY`. |
| Browser CSRF | Browser form handlers call the CSRF validation helper in `app/web.py` / route handlers. |
| API JWT | `app/security.py` issues signed access tokens with `sub`, `iat`, `exp` and `type=access`. |
| API token validation | `app/dependencies.py` validates JWT signature, expiry and token type, then loads the user. It does not compare a password-version fingerprint. |
| Response headers | `SecurityHeadersMiddleware` is registered in `app/main.py`. |
| Browser login throttling | `LoginRateLimitMiddleware` is also registered in `app/main.py`. It counts every matching `POST /login` request, including successful logins. |
| PDF uploads | Application attachments use basic PDF signature/size checks in the Supabase storage helper. The Phase 7 profile-resume route checks the PDF header and EOF marker. |
| Audit events | The former Phase 8 guide proposed an audit ORM model/helper and migration, but the current application integration was not verified. Do not claim audit logging is active based only on that guide. |

## 2. What the former Phase 8 guide proposed

The former root README described these four additions:

- Browser-session credential binding, intended to invalidate browser sessions after a password change.
- A login guard that records failed attempts rather than counting every login request.
- A stricter PDF parser-based upload validation helper.
- A database-backed audit-event model and helper.

The guide also described JWT password-version claims. These are **integration proposals**, not verified active protections in the current application. Before using any of them, check whether the relevant module files and tests exist on the target branch and inspect their current contents.

## 3. Browser-session invalidation

The former guide proposed binding the browser session to a fingerprint derived from the user's password hash. The intended security property is that a password change makes old sessions fail validation on a subsequent request.

This is not currently implemented in the checked `app/web.py` / `app/main.py` flow. If you implement it:

1. Generate a session-specific credential binding after successful authentication.
2. Validate the binding in the common authenticated-user helper on every protected browser request.
3. Clear invalid sessions and require a fresh login.
4. Clear the current session after a successful password change.
5. Keep CSRF validation and role/ownership checks intact.
6. Add tests for normal login, session tampering, password change, expiry and role-protected routes.

Use a dedicated high-entropy secret for session signing in deployment. The current app already supports a dedicated `SESSION_SECRET_KEY`; do not expose either secret in logs or source control.

## 4. JWT password-change invalidation

The current token payload contains `sub`, `iat`, `exp` and `type`. The API dependency verifies the signature and expiry, checks the access-token type and loads the user.

The former guide proposed adding a `pwdv` claim derived from the user's stored password hash, then comparing it with the current hash in `get_current_user`. This is **not present in the checked implementation**.

If implementing this design:

1. Add the fingerprint claim when issuing a token.
2. Validate it after loading the user on every authenticated API request.
3. Reject tokens without the expected claim if backward compatibility is intentionally ended.
4. Add tests proving that a password change invalidates existing tokens.
5. Keep normal JWT signature, algorithm and expiry verification; a custom claim is not a replacement for them.

The current API logout endpoint asks the client to discard its token. It does not revoke a token server-side; a token remains valid until expiry.

## 5. Login throttling

The active `LoginRateLimitMiddleware` is implemented in `app/security_middleware.py` and registered in `app/main.py`. It counts every browser `POST /login` request from a client IP in an in-memory time window. Successful requests also count. This can throttle a user who logs in successfully several times, and the counters are not shared across workers or instances.

The former guide proposed replacing this with a failure-only `LoginGuard` called inside the actual login handlers. Before making that change:

- Ensure both browser and API login handlers are covered.
- Count failed authentication attempts, not successful logins.
- Return a generic authentication error for unknown emails and incorrect passwords.
- Do not trust arbitrary `X-Forwarded-For` values; configure trusted proxy handling deliberately.
- Use shared, atomic storage (for example, Redis) for multi-worker or multi-instance deployments.
- Test the real handlers and concurrent requests.
- Consider the effect of IP-only limits on users sharing a NAT address.

Do not remove the existing middleware until a tested replacement is implemented and wired into the application.

## 6. PDF upload validation

There are currently two separate upload paths:

- Application resume/certificate attachments are sent to Supabase Storage through `app/supabase_storage.py`. That helper restricts document types, checks for non-empty content, applies a 5 MB maximum and checks the `%PDF-` signature.
- Phase 7 candidate profile resumes are written to `ATS_RESUME_STORAGE` (default `private_uploads/resumes`) by `app/routers/phase7.py`. The route checks the filename extension, a 5 MB maximum, the PDF header and an EOF marker near the end of the file.

The former Phase 8 guide proposed using `pypdf` to parse uploads. A parser-based check can reject malformed files more effectively than a header-only check, but pypdf is not a malware scanner and does not make untrusted documents harmless.

If adding parser validation:

1. Validate size before fully reading or parsing the file.
2. Parse in a controlled environment and handle parser exceptions.
3. Do not trust the supplied filename or content type.
4. Use opaque generated storage names.
5. Keep documents private and authorize every download.
6. Consider malware scanning and content-disarm/reconstruction where appropriate.
7. Test malformed, truncated, oversized and non-PDF uploads against both upload routes.

Do not expose the local resume directory through static-file hosting. For Render, local filesystem persistence must be addressed separately; see the Phase 9 guide.

## 7. Database-backed audit logging

The former guide proposed an `AuditEvent` model and an `add_audit_event()` helper, including actor, action, outcome, resource, IP and timestamp fields.

Do not claim this is active until the model is present, imported into Alembic metadata, migrated and called from the actual business handlers.

A safe integration should:

- Record security-relevant events such as login outcomes, password changes, document access, job state changes, application decisions and interview changes.
- Never store passwords, password hashes, access tokens, raw resume content or unnecessary sensitive free-form notes.
- Commit the audit event atomically with the business change where possible.
- Define how audit-write failures affect security-sensitive operations.
- Restrict access to audit records and define retention.

## 8. Migration and test procedure

Before generating or applying an audit migration:

```bash
python -m alembic current
python -m alembic heads
python -m alembic revision --autogenerate -m "add audit events"
```

Inspect the generated migration carefully. It should contain only the intended schema changes. If Alembic proposes unrelated table drops or alterations, do not apply the migration; resolve metadata registration or migration-history drift first.

After review:

```bash
python -m alembic upgrade head
python -m pytest -v
```

The former README mentioned 10 isolated tests for its proposed hardening package. That statement is historical context from the old guide, not a claim about the current test suite or a successful end-to-end integration. Check the current repository tests and GitHub Actions run for actual results.

## 9. Production checklist

Before representing these controls as production-ready, verify and test:

- Dedicated, independently generated JWT and browser-session secrets.
- HTTPS-only secure browser cookies in the deployed environment.
- Explicit trusted-proxy configuration.
- Distributed login throttling with failure-aware semantics.
- JWT/session invalidation behavior after password changes.
- Strict document validation, private storage and authorized downloads.
- MySQL TLS certificate and hostname verification where required.
- Database backups and reviewed migrations.
- Audit-event persistence and access controls.
- End-to-end tests for the real routes, not only isolated helper tests.
