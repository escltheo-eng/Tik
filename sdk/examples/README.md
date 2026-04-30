# Exemples `tik-sdk`

Quatre exemples runnable, en complexité croissante. Tous attendent
un core Tik joignable sur `http://localhost:8200` et une variable
d'environnement `TIK_API_KEY` (cf. `core/scripts/create_api_key.py`).

| # | Fichier                          | Ce qu'il montre                                          |
|---|----------------------------------|----------------------------------------------------------|
| 1 | `01_basic_read.py`               | Health, list entities, derniers signaux. Le « hello world » |
| 2 | `02_streaming_with_hooks.py`     | WebSocket + 4 hooks (signal, crash, fake news, collapse) |
| 3 | `03_zeta_overlay.py`             | Pseudo-overlay sur turbo_v2 (annoté, non runnable)       |
| 4 | `04_full_resilience.py`          | Bot complet : config YAML + cache + breaker + telemetry  |

## Pré-requis

```bash
# Depuis la racine du repo
pip install -e ./sdk

# Variables d'environnement
export TIK_API_KEY=tik_xxxxxxxxxxxx
export TIK_BASE_URL=http://localhost:8200   # défaut si non set
```

## Lancement

```bash
python sdk/examples/01_basic_read.py
python sdk/examples/02_streaming_with_hooks.py
# 03 n'est pas runnable (pseudo-code Zeta)
python sdk/examples/04_full_resilience.py sdk/tik.example.yaml
```
