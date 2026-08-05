import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

from retail_bank_agents.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class AuthContext:
    subject: str
    customer_id: str
    scopes: frozenset[str]
    accounts: frozenset[str]
    step_up_verified: bool = False

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_scope")


def stable_safety_identifier(customer_id: str, secret: str) -> str:
    return hmac.new(secret.encode(), customer_id.encode(), hashlib.sha256).hexdigest()


def _claims_to_context(claims: dict[str, object]) -> AuthContext:
    scope_value = claims.get("scope", "")
    scopes = frozenset(str(scope_value).split())
    accounts_value = claims.get("accounts", [])
    accounts = (
        frozenset(str(value) for value in accounts_value)
        if isinstance(accounts_value, list)
        else frozenset()
    )
    return AuthContext(
        subject=str(claims.get("sub", "")),
        customer_id=str(claims.get("customer_id", "")),
        scopes=scopes,
        accounts=accounts,
        step_up_verified=bool(claims.get("step_up_verified", False)),
    )


async def get_auth_context(
    authorization: Annotated[str | None, Header()] = None,
    x_customer_id: Annotated[str | None, Header()] = None,
    x_scopes: Annotated[str | None, Header()] = None,
    x_accounts: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    if settings.auth_disabled:
        if not x_customer_id:
            raise HTTPException(status_code=401, detail="x-customer-id required in local mode")
        return AuthContext(
            subject=f"local:{x_customer_id}",
            customer_id=x_customer_id,
            scopes=frozenset(
                (x_scopes or "assistant:use accounts:read payments:create payments:approve").split()
            ),
            accounts=frozenset(filter(None, (x_accounts or "acct-001").split(","))),
            step_up_verified=True,
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    if not settings.jwt_jwks_url:
        raise HTTPException(status_code=503, detail="identity_provider_not_configured")
    try:
        token = authorization.removeprefix("Bearer ").strip()
        signing_key = PyJWKClient(settings.jwt_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        context = _claims_to_context(claims)
        if not context.customer_id:
            raise ValueError("customer_id claim missing")
        return context
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc


AuthDependency = Annotated[AuthContext, Depends(get_auth_context)]


_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions", re.I),
    re.compile(r"reveal\s+(the\s+)?(system|developer)\s+prompt", re.I),
    re.compile(r"bypass\s+(security|policy|approval|guardrail)", re.I),
)
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_SENSITIVE_PATTERNS = {
    "cvv": re.compile(r"\b(?:cvv|cvc)\s*[:=-]?\s*\d{3,4}\b", re.I),
    "password": re.compile(r"\b(?:password|passcode|pin)\s*[:=-]\s*\S+", re.I),
    "national_id": re.compile(r"(?<!\d)(?:\d{3}-\d{2}-\d{4}|\d{4}[ -]?\d{4}[ -]?\d{4})(?!\d)"),
}


def _passes_luhn(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def inspect_input(text: str, max_chars: int) -> tuple[str, list[str], bool]:
    """Redact credentials and mark prompt-injection attempts; never log raw input."""
    if len(text) > max_chars:
        return text[:max_chars], ["input_too_long"], True
    violations: list[str] = []
    blocked = False
    sanitized = text
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            violations.append("prompt_injection")
            blocked = True
            break
    for match in reversed(list(_CARD_PATTERN.finditer(sanitized))):
        if _passes_luhn(match.group(0)):
            violations.append("card_number")
            sanitized = (
                sanitized[: match.start()] + "[REDACTED_CARD_NUMBER]" + sanitized[match.end() :]
            )
            blocked = True
    for label, pattern in _SENSITIVE_PATTERNS.items():
        if pattern.search(sanitized):
            violations.append(label)
            sanitized = pattern.sub(f"[REDACTED_{label.upper()}]", sanitized)
            if label in {"cvv", "password", "national_id"}:
                blocked = True
    return sanitized, violations, blocked
