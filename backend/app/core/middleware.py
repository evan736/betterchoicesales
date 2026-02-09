"""Security middleware and utilities."""
import time
import re
from collections import defaultdict
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.config import settings


# ========== IN-MEMORY RATE LIMITER ==========
class RateLimiter:
    """Simple in-memory rate limiter. Tracks requests per IP."""

    def __init__(self):
        self.requests: dict[str, list[float]] = defaultdict(list)
        self.blocked: dict[str, float] = {}

    def _cleanup(self, key: str, window: int):
        now = time.time()
        self.requests[key] = [t for t in self.requests[key] if now - t < window]

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()

        # Check if blocked
        if key in self.blocked:
            if now < self.blocked[key]:
                return True
            else:
                del self.blocked[key]

        self._cleanup(key, window_seconds)

        if len(self.requests[key]) >= max_requests:
            return True

        self.requests[key].append(now)
        return False

    def block(self, key: str, seconds: int):
        self.blocked[key] = time.time() + seconds


# Global rate limiter
rate_limiter = RateLimiter()


# ========== LOGIN ATTEMPT TRACKER ==========
class LoginTracker:
    """Track failed login attempts per IP and username."""

    def __init__(self):
        self.attempts: dict[str, list[float]] = defaultdict(list)
        self.locked: dict[str, float] = {}

    def record_failure(self, key: str):
        now = time.time()
        # Only keep attempts within the lockout window
        window = settings.LOGIN_LOCKOUT_MINUTES * 60
        self.attempts[key] = [t for t in self.attempts[key] if now - t < window]
        self.attempts[key].append(now)

        if len(self.attempts[key]) >= settings.MAX_LOGIN_ATTEMPTS:
            self.locked[key] = now + (settings.LOGIN_LOCKOUT_MINUTES * 60)

    def record_success(self, key: str):
        self.attempts.pop(key, None)
        self.locked.pop(key, None)

    def is_locked(self, key: str) -> bool:
        if key in self.locked:
            if time.time() < self.locked[key]:
                return True
            else:
                del self.locked[key]
                self.attempts.pop(key, None)
        return False

    def remaining_attempts(self, key: str) -> int:
        window = settings.LOGIN_LOCKOUT_MINUTES * 60
        now = time.time()
        recent = [t for t in self.attempts.get(key, []) if now - t < window]
        return max(0, settings.MAX_LOGIN_ATTEMPTS - len(recent))


# Global login tracker
login_tracker = LoginTracker()


# ========== SECURITY HEADERS MIDDLEWARE ==========
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Enable XSS filter
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS (force HTTPS)
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


# ========== RATE LIMIT MIDDLEWARE ==========
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit API requests per IP."""

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Stricter limits for auth endpoints
        if path.startswith("/api/auth/login"):
            if rate_limiter.is_rate_limited(f"login:{client_ip}", max_requests=10, window_seconds=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many login attempts. Please wait before trying again."},
                )
        elif path.startswith("/api/auth/register"):
            if rate_limiter.is_rate_limited(f"register:{client_ip}", max_requests=3, window_seconds=300):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many registration attempts. Please wait."},
                )
        elif path.startswith("/api/sales/extract-pdf"):
            # PDF extraction is expensive
            if rate_limiter.is_rate_limited(f"extract:{client_ip}", max_requests=10, window_seconds=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many extraction requests. Please wait."},
                )
        elif path.startswith("/api/"):
            # General API rate limit: 100 requests per minute
            if rate_limiter.is_rate_limited(f"api:{client_ip}", max_requests=100, window_seconds=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please slow down."},
                )

        return await call_next(request)


# ========== PASSWORD VALIDATION ==========
def validate_password(password: str) -> tuple[bool, str]:
    """Validate password meets security requirements."""
    if len(password) < settings.MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {settings.MIN_PASSWORD_LENGTH} characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    return True, "OK"


# ========== INPUT SANITIZATION ==========
def sanitize_string(value: str, max_length: int = 500) -> str:
    """Basic input sanitization."""
    if not value:
        return value
    # Truncate
    value = value[:max_length]
    # Remove null bytes
    value = value.replace('\x00', '')
    return value.strip()
