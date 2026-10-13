"""🔒 Architectural boundary guards.

These are the invariants the decoupling work exists to establish. They are
checked by scanning source text rather than by importing, because an import
check cannot tell whether *this* package pulled a module in or some other
package already had it in ``sys.modules``.
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def sources(package: str) -> list[Path]:
    files = [p for p in (REPO_ROOT / package).rglob("*.py") if "__pycache__" not in p.parts]
    assert files, f"no sources found under {package}/ -- did the layout change?"
    return files


@pytest.mark.parametrize("package", ["agents", "contracts"])
def test_transport_stays_out_of_the_engine(package: str) -> None:
    """Neither the engine nor the contracts may know what Socket.IO is.

    Graph nodes narrate through the ``TurnSink`` protocol so the transport can
    become a message bus without touching a node. A stray ``import socketio``
    silently re-couples them.
    """
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in sources(package)
        if "import socketio" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"socketio leaked into {package}/: {offenders}"


# Anything that would make the contracts package undeployable on its own, or
# turn it into a shared kernel forcing lockstep deploys across services.
FORBIDDEN_IN_CONTRACTS = (
    "import socketio",
    "from database",
    "import database",
    "from agents",
    "from api",
    "from tools",
    "from utils",
    "from hephaestus",
    "langchain",
    "sqlalchemy",
)


@pytest.mark.parametrize("forbidden", FORBIDDEN_IN_CONTRACTS)
def test_contracts_package_stays_dependency_free(forbidden: str) -> None:
    """``contracts/`` must stay extractable as a standalone distribution."""
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in sources("contracts")
        if forbidden in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"contracts/ must not reference '{forbidden}': {offenders}"


def test_gateway_does_not_hardcode_graph_node_names() -> None:
    """Node names are the graph's private business.

    The stream pump used to live in ``api/`` and switch on node names like
    ``dm_narrator_opening``, which meant the gateway knew the DM graph's
    internal topology. It now lives with the engine.
    """
    node_names = ("dm_narrator_opening", "dm_narrator_closing", "npc_narrator")
    offenders = [
        (path.relative_to(REPO_ROOT), name)
        for path in sources("api")
        for name in node_names
        if name in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"graph node names leaked into api/: {offenders}"
