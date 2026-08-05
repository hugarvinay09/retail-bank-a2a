import pytest

from retail_bank_agents.config import Settings


def test_production_refuses_disabled_authentication() -> None:
    settings = Settings(environment="prod", auth_disabled=True, safety_hmac_key="x" * 32)
    with pytest.raises(ValueError, match="AUTH_DISABLED"):
        settings.validate_runtime()


def test_production_requires_strong_safety_hmac() -> None:
    settings = Settings(environment="prod", auth_disabled=False, safety_hmac_key="short")
    with pytest.raises(ValueError, match="SAFETY_HMAC_KEY"):
        settings.validate_runtime()
