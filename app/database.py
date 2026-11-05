
import ssl

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


settings = get_settings()

database_url = URL.create(
    drivername="mysql+pymysql",
    username=settings.DATABASE_USER,
    password=settings.DATABASE_PASSWORD,
    host=settings.DATABASE_HOST,
    port=settings.DATABASE_PORT,
    database=settings.DATABASE_NAME,
)

connect_args = {}

if settings.DATABASE_SSL_MODE == "verify_identity":
    if not settings.DATABASE_SSL_CA:
        raise ValueError(
            "DATABASE_SSL_CA must be configured "
            "when DATABASE_SSL_MODE=verify_identity"
        )

    ssl_context = ssl.create_default_context(
        cafile=settings.DATABASE_SSL_CA
    )

    ssl_context.verify_mode = ssl.CERT_REQUIRED
    ssl_context.check_hostname = True

    connect_args["ssl"] = ssl_context

elif settings.DATABASE_SSL_MODE != "disabled":
    raise ValueError(
        "DATABASE_SSL_MODE must be disabled or verify_identity"
    )

engine = create_engine(
    database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
