"""Which environment this server is: APP_ENV = development | testing | production.

One switch for everything that must behave differently outside production. Anything that is not exactly a known
name counts as development, so a typo can never turn production behaviour (real emails, WhatsApp) on by accident.

development / testing
  - every email goes ONLY to DEV_EMAIL_TO (nothing is sent if it is empty); WhatsApp is never sent
  - sample data can be loaded; the fake AI (LLM_MOCK=1) can be used; API docs at /docs
  - the web app shows a "Development" ribbon so nobody mistakes it for the real thing
production
  - real recipients (sample candidates and dummy addresses are still never contacted)
  - no sample data loading, no fake AI, no API docs unless API_DOCS=1, no ribbon
"""
import logging
import os

log = logging.getLogger("talentloop")
_ALIASES = {"development": "development", "dev": "development", "local": "development",
            "testing": "testing", "test": "testing", "staging": "testing",
            "production": "production", "prod": "production", "live": "production"}
_raw = (os.getenv("APP_ENV") or "").strip().lower()
APP_ENV = _ALIASES.get(_raw, "development")
IS_PRODUCTION = APP_ENV == "production"
DEV_EMAIL_TO = (os.getenv("DEV_EMAIL_TO") or "").strip().lower()
API_DOCS = not IS_PRODUCTION or os.getenv("API_DOCS") == "1"

if _raw and _raw not in _ALIASES:
    log.warning("APP_ENV=%r is not development, testing or production: running as development", _raw)


def allowed_in_dev(name: str) -> bool:
    """A development-only switch (e.g. LLM_MOCK, ALLOW_SAMPLE_DATA): on only outside production."""
    on = os.getenv(name) == "1"
    if on and IS_PRODUCTION:
        log.error("%s=1 is ignored in production", name)
    return on and not IS_PRODUCTION


def public() -> dict:
    return {"env": APP_ENV, "production": IS_PRODUCTION}
