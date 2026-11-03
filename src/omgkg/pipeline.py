"""Query -> RAG -> KG -> LLM -> Answer."""

from omgkg.generation.answer import LLM, Answer, answer
from omgkg.graph.knowledge_graph import KnowledgeGraph
from omgkg.retrieval.base import Retriever


def ask(
    question: str,
    rag: Retriever,
    kg: KnowledgeGraph | None,
    llm: LLM,
    k: int = 5,
) -> Answer:
    """``kg=None`` skips the graph: the text-only baseline on the same question."""
    evidence = rag.retrieve(question, k)
    if kg is not None:
        evidence = kg.expand(evidence)
    return answer(question, evidence, llm)
