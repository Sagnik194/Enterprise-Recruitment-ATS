
import pytest

from app.security_middleware import LoginRateLimitMiddleware


@pytest.fixture(autouse=True)
def reset_login_rate_limiter():
    """
    Reset rate-limit counters before each test.

    This prevents unrelated tests from sharing
    in-memory login attempt history.
    """
    instances = []

    # Capture middleware instances currently registered
    # on the main application.
    from app.main import app

    middleware_stack = app.middleware_stack

    current = middleware_stack

    while current is not None:
        if isinstance(current, LoginRateLimitMiddleware):
            instances.append(current)

        current = getattr(current, "app", None)

    for middleware in instances:
        with middleware.lock:
            middleware.attempts.clear()

    yield

    for middleware in instances:
        with middleware.lock:
            middleware.attempts.clear()
