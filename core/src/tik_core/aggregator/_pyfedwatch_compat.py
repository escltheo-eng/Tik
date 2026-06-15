"""Shim de compatibilité pour pyfedwatch (ADR-029).

pyfedwatch 1.2.0 importe au niveau module deux dépendances inutiles pour notre
usage et problématiques :

- `pandas_datareader` (épinglé 0.10.0) — **casse à l'import** contre pandas>=2.2
  (`deprecate_kwarg() missing argument`). Utilisé uniquement par le lecteur de
  données par défaut et par la récupération FRED du range de taux ; on fournit
  notre propre `user_func` et on passe `watch_rate_range` explicitement, donc on
  ne l'appelle jamais.
- `matplotlib` — utilisé uniquement par les méthodes de plot du calendrier ; on
  ne plotte pas.

On installe des modules factices dans `sys.modules` AVANT d'importer pyfedwatch :
les `import` de pyfedwatch sont satisfaits sans tirer les vraies libs (cf.
Dockerfile : `pip install --no-deps pyfedwatch`). Les vraies dépendances du chemin
réellement exécuté (pandas / numpy / python-dateutil / holidays) sont, elles,
bien installées via pyproject.

Ce module isole entièrement la bidouille : le reste du code importe simplement
`from tik_core.aggregator._pyfedwatch_compat import FedWatch`.
"""

from __future__ import annotations

import sys
import types


def _ensure_stub(name: str) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return mod


# Stubs AVANT l'import de pyfedwatch.
_ensure_stub("pandas_datareader")
_mpl = _ensure_stub("matplotlib")
_mpl.patches = _ensure_stub("matplotlib.patches")
_ensure_stub("matplotlib.pyplot")

from pyfedwatch.fedwatch import FedWatch  # noqa: E402  (import après les stubs)

__all__ = ["FedWatch"]
