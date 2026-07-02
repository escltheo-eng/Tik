"""Le schéma OpenAPI est masqué en production (audit 2026-07-02).

`docs`/`redoc` étaient déjà désactivés en prod mais `/openapi.json` restait
public : sur le VPS exposé `IP:8200`, un scanner récupérait la description
complète des routes. Désormais `openapi_url=None` en production, comme
docs/redoc. En dev, l'override `custom_openapi` (Bug 5) reste fonctionnel.
"""

from tik_core.config import get_settings
from tik_core.main import create_app


def _fresh_app_for_env(monkeypatch, env: str):
    monkeypatch.setenv("TIK_ENV", env)
    get_settings.cache_clear()
    try:
        return create_app()
    finally:
        get_settings.cache_clear()


def test_openapi_hidden_in_production(monkeypatch):
    prod_app = _fresh_app_for_env(monkeypatch, "production")
    assert prod_app.openapi_url is None
    assert prod_app.docs_url is None
    assert prod_app.redoc_url is None


def test_openapi_available_in_development(monkeypatch):
    dev_app = _fresh_app_for_env(monkeypatch, "development")
    assert dev_app.openapi_url == "/openapi.json"
    assert dev_app.docs_url == "/docs"
    # Bug 5 : le security scheme bearerAuth doit rester déclaré en dev.
    schema = dev_app.openapi()
    assert "bearerAuth" in schema["components"]["securitySchemes"]
