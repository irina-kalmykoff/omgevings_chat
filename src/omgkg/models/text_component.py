"""The shared evidence layer: one structural unit of legal text (PLAN.md section 6).

Carries text and structural provenance only. DSO semantic annotations (activities,
locations, ...) are deliberately absent so the LLM-induced pipeline cannot see them
(PLAN.md constraint 3); they belong in a separate type.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omgkg.models.provenance import Provenance


class Heading(BaseModel):
    """One enclosing structural level, e.g. a Hoofdstuk with its heading."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(min_length=1)
    heading: str


class Paragraph(BaseModel):
    """A lid inside an article, as a character span of the article's text."""

    model_config = ConfigDict(frozen=True)

    w_id: str = Field(min_length=1)
    e_id: str | None = None
    number: str
    start: int = Field(ge=0)
    end: int

    @model_validator(mode="after")
    def _span_is_ordered(self) -> "Paragraph":
        if self.end < self.start:
            raise ValueError("Paragraph end lies before its start")
        return self


class TextComponent(BaseModel):
    """An article, appendix or explanatory note with its provenance.

    Document, version and structural path live on ``provenance`` only, so they
    cannot drift from the copy a retriever cites.
    """

    model_config = ConfigDict(frozen=True)

    # FRBR expression + "#" + wId: unique across documents, not only within one.
    id: str = Field(min_length=1)
    kind: Literal["article", "appendix", "explanatory_note"]
    number: str
    heading: str
    context: list[Heading]
    text: str = Field(min_length=1)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def _paragraphs_inside_text(self) -> "TextComponent":
        if any(p.end > len(self.text) for p in self.paragraphs):
            raise ValueError("Paragraph span runs past the component text")
        return self
