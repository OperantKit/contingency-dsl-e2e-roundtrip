"""Point the harness at a contingency-dsl conformance tree for the test run.

An explicit ``E2E_CONFORMANCE_ROOT`` wins. Otherwise the first ancestor of
this package that holds ``contingency-dsl/conformance`` or
``apps/core/contingency-dsl/conformance`` is used, so the suite runs both
from a sibling checkout and from a nested monorepo layout.
"""

from __future__ import annotations

import os
from pathlib import Path

from contingency_dsl_e2e_roundtrip.config import ENV_CONFORMANCE_ROOT


_CANDIDATES = (
    Path("contingency-dsl") / "conformance",
    Path("apps") / "core" / "contingency-dsl" / "conformance",
)


def _find_conformance_root() -> Path | None:
    package_root = Path(__file__).resolve().parent.parent
    for ancestor in package_root.parents:
        for rel in _CANDIDATES:
            candidate = ancestor / rel
            if candidate.is_dir():
                return candidate
    return None


if not os.environ.get(ENV_CONFORMANCE_ROOT):
    _found = _find_conformance_root()
    if _found is not None:
        os.environ[ENV_CONFORMANCE_ROOT] = str(_found)
