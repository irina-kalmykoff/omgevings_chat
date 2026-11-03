"""The LLM step: a cited answer from the RAG + KG evidence.

The model sees numbered sources; graph-added ones are labelled with how they
relate to a retrieved source, which is the information the graph contributes.
Citations ``[n]`` in the answer are resolved back to the evidence they name.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from omgkg.models import Evidence

PROMPT = Path(__file__).parents[3] / "configs" / "prompts" / "answer.txt"
CITATION = re.compile(r"\[(\d+)\]")
EFFECT = {
    "exemption": "vrijstelling",
    "prohibition": "verbod",
    "permission": "toestemming",
    "obligation": "plicht",
}


class LLM(Protocol):
    def complete(self, instructions: str, prompt: str) -> str: ...


class OpenAIModel:
    def __init__(self, model: str, client: OpenAI | None = None) -> None:
        self._model = model
        self._client = client or OpenAI()  # reads OPENAI_API_KEY

    def complete(self, instructions: str, prompt: str) -> str:
        response = self._client.responses.create(
            model=self._model,
            instructions=instructions,
            input=prompt,
            temperature=0,
            store=False,  # legal questions from users are not kept at OpenAI
        )
        return response.output_text


class Answer(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    text: str
    evidence: list[Evidence]
    # The evidence the answer cites, in order of first citation.
    citations: list[Evidence]


def _label(item: Evidence, number: dict[str, int]) -> str:
    """How a graph-added source relates to the source that pulled it in."""
    if not item.graph_paths:
        return ""
    path = item.graph_paths[0]
    relation, *detail = path.relations[0].split(":")
    n = number.get(path.node_ids[0])
    if n is None:
        return ""
    kind = "uitzondering" if detail[:1] == ["exception"] else "inperking"
    text = {
        "overridden_by": f"maakt een {kind} op [{n}]",
        "overrides": f"[{n}] maakt hierop een {kind}",
        "refers_to": f"waarnaar [{n}] verwijst",
    }[relation]
    if len(detail) > 1 and detail[1] in EFFECT:
        text += f"; netto effect: {EFFECT[detail[1]]}"
    return f" (via kennisgraaf: {text})"


def build_prompt(question: str, evidence: Sequence[Evidence]) -> str:
    number = {e.text_component_id: i for i, e in enumerate(evidence, start=1)}
    sources = "\n\n".join(
        f"[{i}] {e.provenance.structural_path or e.text_component_id}"
        f"{_label(e, number)}\n{e.text}"
        for i, e in enumerate(evidence, start=1)
    )
    return f"Vraag: {question}\n\nBronnen:\n\n{sources}"


def answer(question: str, evidence: Sequence[Evidence], llm: LLM) -> Answer:
    text = llm.complete(
        PROMPT.read_text(encoding="utf-8"), build_prompt(question, evidence)
    )
    cited: dict[int, Evidence] = {}
    for match in CITATION.finditer(text):
        n = int(match.group(1))
        if 1 <= n <= len(evidence):  # a number outside the sources is ignored
            cited.setdefault(n, evidence[n - 1])
    return Answer(
        question=question,
        text=text,
        evidence=list(evidence),
        citations=list(cited.values()),
    )
