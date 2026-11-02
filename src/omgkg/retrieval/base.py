"""The retriever interface every configuration implements (PLAN.md section 7)."""

from typing import Protocol

from omgkg.models import Evidence


class Retriever(Protocol):
    def retrieve(self, query: str, k: int) -> list[Evidence]: ...
