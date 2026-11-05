# Phase 8 ATS hardening — installation and integration

This package adds **four complete modules** and **10 passing isolated tests**. It intentionally does not overwrite your existing `app/main.py`, `app/web.py`, `app/security.py`, `app/dependencies.py`, `app/routers/auth.py`, `app/routers/phase7.py`, or `app/models.py`, because their exact current contents were not supplied. The snippets below are required integration steps; the new modules alone do not protect existing endpoints.

## 1. Install

From your activated `.venv` at `Enterprise-Recruitment-ATS`:

```powershell
python -m pip install "pypdf>=5,<7"
```

Copy `app/hardening.py`, `app/login_guard.py`, `app/pdf_guard.py`, `app/audit.py` into your existing `app` folder. Copy `tests/test_hardening.py` into `tests`. Run:

```powershell
python -m pytest tests/test_hardening.py -v
```

## 2. Configure secrets

Use a stable, random, >=32-byte secret in `.env` for `JWT_SECRET_KEY`, and a **different** random `SESSION_SECRET_KEY`. Generate each with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Never print secrets in logs or commit `.env`. Rotate only when ready to invalidate existing sessions/tokens.

In `app/main.py`, use your current configuration object and read `SESSION_SECRET_KEY` with `os.environ["SESSION_SECRET_KEY"]` in deployed environments. Configure `SessionMiddleware` with `max_age=3600`, `same_site="lax"`, and `https_only=True` **when served over HTTPS**. `max_age` is a cookie expiry setting, not server-side credential invalidation.

## 3. Browser session expiry and password-change invalidation (REQUIRED integration)

At the top of `app/web.py`:

```python
import os
from app.hardening import new_browser_session, validate_browser_session

CREDENTIAL_BINDING_SECRET = os.environ["JWT_SECRET_KEY"]
```

In the **successful** `POST /login` branch, **replace** the existing `request.session["user_id"] = user.id` assignment with:

```python
new_browser_session(
    request.session,
    user.id,
    user.password_hash,
    CREDENTIAL_BINDING_SECRET,
)
```

In your existing `current_user(request, db)` helper, immediately **after** loading the user by ID, add:

```python
if user is None or not validate_browser_session(
    request.session, user.password_hash, CREDENTIAL_BINDING_SECRET
):
    request.session.clear()
    return None
```

Keep existing CSRF and role checks. In password-change handlers, after `user.password_hash = hash_password(new_password)` and committing, clear the browser session (`request.session.clear()`) and require a fresh login. The hash-version check will also invalidate other browser sessions on their next request.

**Important:** If you use a preexisting user session for CSRF on the login form, `new_browser_session` rotates that session only after CSRF validation and successful authentication.

## 4. JWT password-change invalidation (REQUIRED integration)

Your existing `app/security.py` likely has `create_access_token` and your `app/dependencies.py` decodes JWTs. Keep their existing claim generation, expiration, algorithm and signature verification intact. **Add** a `pwdv` claim **at the moment of issuing each access token**, computed from the authenticated user's stored password hash:

```python
from app.hardening import password_fingerprint
claims["pwdv"] = password_fingerprint(user.password_hash, JWT_SECRET_KEY)
```

Here `claims` is your existing JWT payload dictionary and `JWT_SECRET_KEY` is the exact secret used for signing the token. If your helper accepts only a `subject`, extend it to accept a `password_version` argument and pass it from `POST /auth/login`.

After JWT signature/expiry validation and after retrieving the user in `get_current_user`, reject the token unless:

```python
from app.hardening import validate_jwt_password_version
if not validate_jwt_password_version(payload, user.password_hash, JWT_SECRET_KEY):
    raise credentials_exception  # your existing HTTP 401 exception
```

This deliberately invalidates older tokens without `pwdv`. It is **not** sufficient to change only the login handler: the JWT verification dependency must check the claim on every authenticated request.

## 5. Login hardening (REQUIRED integration)

The original Phase 8 `LoginRateLimitMiddleware` counts every POST to `/login` (including successful logins) and has already caused cascading test failures. For a failure-only approach, **remove that middleware registration from `app/main.py`**, retain `SecurityHeadersMiddleware`, and use `LoginGuard` inside your actual login handlers:

```python
from app.login_guard import LoginGuard
browser_login_guard = LoginGuard(max_failures=5, window_seconds=300)
api_login_guard = LoginGuard(max_failures=5, window_seconds=300)
```

Use module-level guards, not a new guard per request. In each login handler, after validating CSRF (for browser login) and before verifying the password:

```python
ip = request.client.host if request.client else "unknown"
key = ip  # conservative: never trust unverified X-Forwarded-For
if not browser_login_guard.allowed(key):
    raise HTTPException(status_code=429, detail="Too many login attempts")
```

For a failed login (whether the email is unknown or the password is wrong):

```python
browser_login_guard.record_failure(key)
# Return the same generic error for both cases.
```

For a successful login:

```python
browser_login_guard.record_success(key)
```

Use `api_login_guard` for `/auth/login` analogously. **Do not leak whether an email exists**. Avoid logging passwords, submitted forms, tokens, resume contents or raw credentials. For unknown users, verify a precomputed dummy password hash to reduce timing differences (calculate it once on startup, not per request). In production, replace the in-memory guard with a Redis-backed atomic rate limiter and configure trusted proxy IP handling. An IP-only limit may affect users sharing a NAT address.

For testing, isolate/reset guards per test, or inject a fresh guard. Never globally disable production rate limiting just to make tests pass.

## 6. Resume upload validation (REQUIRED integration)

In the existing Phase 7 upload handler, **replace the previous header-only PDF validation** with:

```python
from app.pdf_guard import read_resume_upload, InvalidResume
try:
    content = read_resume_upload(resume)
except InvalidResume as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Use the same variable name as your existing `UploadFile` argument (e.g. `resume`). Do not trust `UploadFile.content_type` or the original filename for the stored path. Use random UUID storage names, a non-public upload directory, restricted file permissions, and authorized download endpoints with `Content-Disposition: attachment`. **Do not serve the uploads directory via `StaticFiles`.**

**Breaking-test note:** Your earlier `tests/test_phase7.py` used `b'%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF'`, which is not a valid PDF. Replace that fixture with a real PDF created using `pypdf.PdfWriter`, as in `tests/test_hardening.py`. The strict validator will correctly reject the old fake fixture. pypdf is a parser, **not** a malware scanner; add malware scanning and content sanitization before public deployment.

## 7. Database-backed audit logging

`app/audit.py` contains a complete `AuditEvent` ORM model and `add_audit_event()` helper. It stores action, outcome, actor ID, resource ID/type, IP and timestamp; **never store secrets, password hashes, tokens, raw resume content or sensitive free-form notes**.

Add `import app.audit` near the top of `migrations/env.py`, before `target_metadata` is assigned. If your migrations directory is called `alembic` instead, edit `alembic/env.py`.

```powershell
python -m alembic current
python -m alembic heads
python -m alembic revision --autogenerate -m "add audit events"
```

**Inspect the generated migration carefully.** It should only create `audit_events` and its indexes. If Alembic proposes dropping or altering unrelated tables, **do not apply it**. Resolve metadata/model registration drift first. Then:

```powershell
python -m alembic upgrade head
```

In a successful recruiter mutation, before your existing `db.commit()`:

```python
from app.audit import add_audit_event
add_audit_event(
    db,
    action="interview.schedule",
    outcome="success",
    actor_user_id=recruiter.id,
    resource_type="interview",
    resource_id=interview.id,
    ip_address=request.client.host if request.client else None,
)
```

Ensure the interview has an ID (`db.flush()`) before recording the event. The audit event and business change then commit **atomically**. For authentication failures (no existing business transaction), use a short separate database transaction and record only a generic outcome. Handle audit write failures according to your policy; for security-sensitive business mutations, fail closed rather than silently dropping the audit event.

Recommended actions: `auth.login_success`, `auth.login_failure`, `auth.password_change`, `resume.upload`, `resume.download`, `job.close`, `job.reopen`, `application.shortlist`, `application.reject`, `interview.schedule`, `interview.reschedule`, `interview.cancel`, `interview.result`.

## 8. Run tests and verify

```powershell
python -m pytest tests/test_hardening.py -v
python -m pytest -v
```

The package's **10 isolated tests were run and passed**. Full application integration tests have not been run against your local ATS repository. After integrating, add end-to-end tests for the real login handlers, both JWT and browser invalidation, actual resume upload route, audit transaction atomicity, and database migrations. A passing isolated suite does not establish that those routes are already hardened.
