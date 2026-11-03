"""Pydantic types shared across modules.

TextComponent, Node, Edge, Provenance, Evidence, RunRecord.
"""

from omgkg.models.evidence import Evidence, GraphPath
from omgkg.models.provenance import Provenance

__all__ = ["Evidence", "GraphPath", "Provenance"]
