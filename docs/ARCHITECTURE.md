
# System Architecture

The Sagniq Enterprise Recruitment & Applicant Tracking System
uses a FastAPI backend with a server-rendered browser interface,
REST API endpoints, MySQL persistence and document storage.

## Architecture Diagram

```mermaid
flowchart TB
    C["Candidate"]
    R["Recruiter"]
    A["Administrator"]

    subgraph APP["FastAPI Application"]
        WEB["Browser Interface<br/>Jinja2 Templates"]
        API["REST API<br/>FastAPI Routers"]
        AUTH["Authentication<br/>Sessions and JWT"]
        LOGIC["Application Workflows<br/>Jobs, Applications, Interviews"]
        MODELS["SQLAlchemy Models"]
    end

    DB[("MySQL Database")]

    STORAGE["Supabase Storage<br/>Application Attachments"]
    LOCAL["Local Filesystem<br/>Phase 7 Profile Resumes"]

    C --> WEB
    R --> WEB
    A --> WEB

    WEB --> AUTH
    WEB --> LOGIC
    API --> AUTH
    API --> LOGIC

    LOGIC --> MODELS
    MODELS --> DB

    LOGIC --> STORAGE
    LOGIC --> LOCAL
```

## Main Components

- **Browser Interface:** Jinja2 templates provide the user-facing pages.
- **REST API:** FastAPI routers expose application endpoints.
- **Authentication:** Browser sessions and JWT-based API authentication.
- **Business Workflows:** Job, application and interview operations.
- **Database:** MySQL accessed through SQLAlchemy.
- **Application Documents:** Supabase Storage.
- **Phase 7 Profile Resumes:** Local filesystem storage.

## Important Storage Distinction

The application attachment workflow and Phase 7 profile-resume
workflow use different storage backends. They should not be
treated as one unified document-storage system.
