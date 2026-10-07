"""The repository skeleton is importable and the test-suite guards are active."""

import importlib
import socket

import pytest
from pytest_socket import SocketBlockedError

PACKAGES = [
    "omgkg",
    "omgkg.models",
    "omgkg.ingest",
    "omgkg.ingest.dso",
    "omgkg.graph",
    "omgkg.graph.dso_native",
    "omgkg.graph.llm_induced",
    "omgkg.graph.hybrid",
    "omgkg.graph.fallback",
    "omgkg.retrieval",
    "omgkg.generation",
    "omgkg.evaluation",
    "omgkg.experiments",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    importlib.import_module(name)


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_network_is_disabled() -> None:
    # Experiments and tests must run from the local snapshot, never a live API.
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
