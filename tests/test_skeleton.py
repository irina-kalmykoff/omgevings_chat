"""Every module imports, and the test-suite guards are active."""

import importlib
import socket

import pytest
from pytest_socket import SocketBlockedError

PACKAGES = [
    "omgkg",
    "omgkg.cli",
    "omgkg.pipeline",
    "omgkg.models",
    "omgkg.ingest.dso.stop_tpod",
    "omgkg.retrieval.omgevingschat",
    "omgkg.retrieval.qdrant",
    "omgkg.graph.build",
    "omgkg.graph.knowledge_graph",
    "omgkg.graph.kg_service",
    "omgkg.generation.answer",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    importlib.import_module(name)


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_network_is_disabled() -> None:
    # Experiments and tests must run from the local snapshot, never a live API.
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
