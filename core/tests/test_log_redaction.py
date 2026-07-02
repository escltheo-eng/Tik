"""Tests du filtre de redaction des clés API dans les logs uvicorn.

Audit 2026-07-02 (constat A-1, confirmé en E2E) : l'auth WebSocket passe la
clé en query string et uvicorn logue l'URL complète → clé en clair dans les
logs d'accès. Le filtre `ApiKeyRedactionFilter` (main.py) masque la valeur
dans `record.msg` ET `record.args`.
"""

import logging

from tik_core.main import ApiKeyRedactionFilter, _configure_logging, _redact_api_key

SECRET = "tik_KE3PH4CzgeEUp0lUy9teq11VNjbWZS8hssTppRFY78k"  # noqa: S105 — factice


def test_redact_api_key_masks_value_and_keeps_rest():
    url = f"/api/v1/ws/signals?api_key={SECRET}&entity=BTC&horizon=swing"
    out = _redact_api_key(url)
    assert SECRET not in out
    assert "api_key=***REDACTED***" in out
    assert "&entity=BTC&horizon=swing" in out


def test_redact_api_key_noop_without_key():
    assert _redact_api_key("/api/v1/health") == "/api/v1/health"


def test_filter_redacts_message_and_args_like_uvicorn_access():
    """uvicorn.access logue via un msg de format et le path dans args."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            f"/api/v1/ws/signals?api_key={SECRET}",
            "1.1",
            403,
        ),
        exc_info=None,
    )
    assert ApiKeyRedactionFilter().filter(record) is True  # jamais supprimé
    formatted = logging.Formatter("%(message)s").format(record)
    assert SECRET not in formatted
    assert "***REDACTED***" in formatted
    assert "403" in formatted  # le reste de la ligne est préservé


def test_filter_redacts_plain_message():
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=f'connection open "/api/v1/ws/signals?api_key={SECRET}"',
        args=None,
        exc_info=None,
    )
    ApiKeyRedactionFilter().filter(record)
    assert SECRET not in record.getMessage()


def test_filter_leaves_non_string_args_untouched():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%s %d",
        args=(f"api_key={SECRET}", 200),
        exc_info=None,
    )
    ApiKeyRedactionFilter().filter(record)
    assert record.args[1] == 200
    assert SECRET not in record.args[0]


def test_configure_logging_installs_filter_idempotently():
    _configure_logging("INFO")
    _configure_logging("INFO")  # 2e appel : pas de doublon
    for name in ("uvicorn.access", "uvicorn.error"):
        filters = [
            f for f in logging.getLogger(name).filters if isinstance(f, ApiKeyRedactionFilter)
        ]
        assert len(filters) == 1, f"{name}: {len(filters)} filtres (attendu 1)"
