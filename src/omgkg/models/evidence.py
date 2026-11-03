"""What every retriever returns: source-linked text, never raw triples."""

from pydantic import BaseModel, ConfigDict, Field

from omgkg.models.provenance import Provenance


class GraphPath(BaseModel):
    """The graph path from the query's concepts to a piece of evidence."""

    model_config = ConfigDict(frozen=True)

    node_ids: list[str] = Field(min_length=1)
    relations: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    """One ranked text passage with its provenance."""

    model_config = ConfigDict(frozen=True)

    text_component_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float | None = None
    rank: int = Field(ge=1)
    provenance: Provenance
    # Empty for the text baseline (configuration A).
    graph_paths: list[GraphPath] = Field(default_factory=list)
