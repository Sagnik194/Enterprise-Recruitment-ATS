# Phase 9 — Render + external MySQL (no Docker)

## 1. Prepare your project
Copy `render.yaml`, `.env.render.example`, `.github/workflows/ci.yml`, and `scripts/check_migrations.py` into the project root, retaining paths. Keep existing `app/`, `tests/`, `migrations/`, `alembic.ini`, and `requirements.txt`.

Verify `requirements.txt` includes `uvicorn`, `pymysql`, `cryptography`, `alembic`, `pytest`, `httpx`, `jinja2`, `itsdangerous`, `python-multipart`, `pydantic-settings`, and `pypdf` (as appropriate for your app).

## 2. Confirm a fresh MySQL database can be migrated
Your earlier Alembic baseline may be empty. If it is, `alembic upgrade head` on a blank MySQL database will NOT create your original users/jobs/applications tables. Fix the migration history using a carefully reviewed baseline revision before attempting production deployment. Do not run `alembic stamp head` on an empty database. Back up any existing database before migration edits. Test against a disposable blank database first.

## 3. Create managed MySQL
Create a managed MySQL instance at Aiven or another provider. Note host, port, user, password, database, and CA certificate/TLS requirements. Allow access from Render according to provider policy. Some services require a paid plan or additional networking configuration.

Your existing `app/database.py` uses `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME`. If the provider requires TLS, update the SQLAlchemy engine connection options according to the provider's certificate documentation. Never disable certificate verification for production.

## 4. Deploy on Render
Push the configuration to GitHub. In Render: New > Blueprint > select repository > review plan and env vars > Deploy. The Blueprint is set to `starter` to avoid relying on free-tier availability; change only after checking available plans. Enter real MySQL credentials in Render's Environment panel. `JWT_SECRET_KEY` and `SESSION_SECRET_KEY` are generated independently by Render. The web service listens on `$PORT` and exposes `/health`.

IMPORTANT: The Blueprint deliberately disables automatic deployments. Deploy manually only after GitHub Actions tests pass. If you enable auto-deploy, GitHub Actions tests do not necessarily gate Render deployment; configure an explicit deployment gate before claiming CD is gated by CI.

## 5. Apply migrations
From a secure machine with database connectivity and the correct environment variables set, run `python -m alembic upgrade head` only after confirming the migration chain creates the entire schema. Then run `python -m scripts.check_migrations`. Avoid automatically running migrations in every web worker at startup.

## 6. Resume persistence
Do NOT store candidate resumes on Render's ephemeral local filesystem. Use S3-compatible object storage or a persistent disk on an eligible paid plan, with private access and authorization checks. The existing Phase 7 upload route must be adapted to that storage before accepting real candidate resumes.

## 7. CI
GitHub Actions runs `pytest` on pushes and PRs. It assumes tests use isolated SQLite fixtures, as in earlier phases. If tests depend on a real MySQL service, add a MySQL service to the workflow. Do not include production credentials in GitHub Actions.

## 8. Validate
- Render service: `/health`, `/login`, `/docs`
- Browser login for candidate/recruiter/admin
- Application creation and interview scheduling
- CSRF and access-control tests
- Audit logging and migrations
- HTTPS-only secure session cookies
- Private resume storage

## Security notes
The original in-memory rate limiter is not distributed across workers or instances. Use shared backing storage for production. Confirm secure session cookies, proxy trust settings, TLS to MySQL, backups, and logging retention. The start command's proxy headers setting assumes Render is the only trusted ingress; restrict forwarded IP trust if deployment topology changes.
