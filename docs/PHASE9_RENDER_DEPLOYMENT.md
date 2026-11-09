# Phase 9 deployment — Render and external MySQL

This document preserves the useful deployment instructions from the former `README_PHASE9_RENDER.md`, updated to match the checked-in Render Blueprint and application configuration.

## 1. Deployment configuration in this repository

The checked-in `render.yaml` defines:

- A Render Python web service named `enterprise-recruitment-ats`.
- The `starter` plan.
- Build command: `pip install -r requirements.txt`.
- Start command: Uvicorn serving `app.main:app` on Render's `$PORT`, with proxy headers enabled and forwarded IPs accepted from `*`.
- Health check path: `/health`.
- Automatic deployment disabled (`autoDeployTrigger: off`).
- Python version `3.12.10`.
- Database host, port, user, password and name environment variables.
- Generated JWT and session secrets.
- JWT algorithm and access-token expiry settings.

Review the current Render dashboard and service environment before assuming the deployed service has the same values as this file. The Blueprint does not declare `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_STORAGE_BUCKET`, `DATABASE_SSL_MODE` or `DATABASE_SSL_CA`; set those in the service environment when the corresponding application features require them.

## 2. Prepare the repository

The project already contains the Render Blueprint, dependency file, GitHub Actions workflow, Alembic configuration and migration-check script. Keep their paths intact when deploying.

Install dependencies locally before deployment:

```bash
python -m pip install -r requirements.txt
```

The pinned requirements file includes the runtime and test dependencies used by the current application. Do not add dependency names from the old deployment checklist without checking whether the current requirements already include them.

## 3. Confirm the database migration history

The previous deployment notes warned that an empty or incomplete Alembic baseline can leave a newly provisioned database without the application's tables. Treat migration history as a release-critical check.

Before using a fresh managed database:

1. Back up any database containing data.
2. Inspect the revisions in `migrations/versions/`.
3. Confirm that the migration chain creates the complete schema from an empty database.
4. Test `python -m alembic upgrade head` against a disposable, blank MySQL database.
5. Run `python -m scripts.check_migrations` after applying migrations.

Do not assume that `alembic upgrade head` creates missing tables if the migration chain contains only a baseline or if the database was stamped without the schema being created. Do not run `alembic stamp head` on an empty database as a substitute for migrations.

## 4. Configure managed MySQL

Provision a managed MySQL database with a provider such as Aiven or another compatible service. Obtain:

- Host
- Port
- Database name
- Username
- Password
- CA certificate and TLS requirements, if applicable

The application constructs a `mysql+pymysql` SQLAlchemy URL from `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_USER`, `DATABASE_PASSWORD` and `DATABASE_NAME`.

For CA-verified TLS, configure:

```text
DATABASE_SSL_MODE=verify_identity
DATABASE_SSL_CA=/path/to/provider-ca.pem
```

The engine creates an SSL context that requires a trusted certificate and verifies the hostname. Ensure the CA file is available at the configured path in the deployed environment. Do not disable certificate verification to work around a TLS error in production.

## 5. Configure Render

In the Render dashboard:

1. Create or open the Blueprint-backed service for this repository.
2. Review the plan, build command, start command and health-check path.
3. Add the managed MySQL credentials as environment variables.
4. Ensure `JWT_SECRET_KEY` and `SESSION_SECRET_KEY` are independently generated, high-entropy values.
5. Set `SESSION_HTTPS_ONLY=true` for HTTPS deployment.
6. Add `DATABASE_SSL_MODE` and `DATABASE_SSL_CA` when the database provider requires verified TLS.
7. Add `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and, if needed, `SUPABASE_STORAGE_BUCKET` for the Supabase-backed application attachment flow.
8. Review the actual service environment and deploy.

The checked-in Blueprint disables automatic deployment. This is a manual deployment configuration, not evidence that GitHub Actions automatically gates deployments.

## 6. Candidate document persistence

The main application submission flow uses Supabase Storage for resume and optional certificate attachments. Configure a private bucket and the required Supabase server-side environment variables before relying on this workflow in a deployed environment.

The separate Phase 7 profile-resume route writes files to a local directory configured by `ATS_RESUME_STORAGE`, defaulting to `private_uploads/resumes`. A Render service's ordinary local filesystem should not be treated as durable storage across service replacement or redeployment.

Before using the Phase 7 profile-resume route for production documents, migrate it to a durable private object-storage backend or configure an appropriate persistent disk and validate access controls and backup behavior. Do not assume that enabling Supabase for application attachments automatically changes the Phase 7 profile-resume storage path.

## 7. Continuous integration

The GitHub Actions workflow at `.github/workflows/ci.yml`:

- Runs on pushes and pull requests targeting `main`.
- Uses Ubuntu and Python 3.12.
- Installs `requirements.txt`.
- Runs `python -m pytest -v`.

It defines database environment variables but does not start a MySQL service container. Confirm whether tests use isolated fixtures or require a database service before treating CI as a MySQL integration test.

The workflow does not, by itself, gate Render deployment. Because the Blueprint has automatic deployment disabled, deployment is performed separately. If you later enable automatic deployment, configure an explicit deployment gate rather than assuming a passing Actions workflow is enforced by Render.

## 8. Post-deployment verification

After deployment, verify:

- `/health` reports a healthy status and successful database connection.
- `/login` loads and browser session cookies have the expected HTTPS settings.
- `/docs` exposes the FastAPI API documentation as expected.
- Candidate, recruiter and administrator login/authorization flows work.
- Job creation, browsing and status changes work.
- Application submission and recruiter review work.
- Supabase uploads and authorized document access work.
- Phase 7 profile-resume behavior is consistent with the configured persistence backend.
- Interview scheduling, rescheduling, cancellation and result recording work.
- Database migrations are at the repository's current Alembic head.
- GitHub Actions has a successful current run.

The health endpoint checks database connectivity; it does not verify Supabase storage, candidate workflows or all application routes.

## 9. Operational security notes

- Keep production secrets out of Git and GitHub Actions logs.
- Use TLS certificate verification for managed MySQL where required.
- Use private object storage and authorization checks for candidate documents.
- The current browser login limiter is in-memory and counts all browser login POST requests. It is not a distributed, failure-only production rate limiter.
- The Uvicorn command trusts forwarded headers from `*`. Restrict trusted proxy IPs to the actual ingress topology before using a deployment path where untrusted clients can reach the app directly.
- Back up the database and test restore procedures.
- Review migrations before applying them to production.
- Keep Render environment configuration synchronized with the settings actually read by the application.

## Live service

https://enterprise-recruitment-ats.onrender.com
