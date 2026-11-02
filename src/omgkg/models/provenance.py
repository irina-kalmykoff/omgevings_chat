"""Where a piece of evidence, node or edge comes from (PLAN.md section 6)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """A reference to the origin of a legal claim: a DSO resource or a passage."""

    model_config = ConfigDict(frozen=True)

    source_type: Literal["dso_resource", "legal_text_passage"]
    document_id: str = Field(min_length=1)
    document_version_id: str | None = None
    # The STOP wId of the article or lid; OmgevingsChat calls it componentId.
    text_component_id: str | None = None
    structural_path: str = ""
    source_uri: str | None = None
    # Links to data/manifests/ (our corpus) or names the external index snapshot.
    snapshot_id: str = Field(min_length=1)
