"""Pydantic types shared across modules.

TextComponent, Node, Edge, Provenance, Evidence, RunRecord.
"""

from omgkg.models.evidence import Evidence, GraphPath
from omgkg.models.provenance import Provenance
from omgkg.models.text_component import Heading, Paragraph, TextComponent

__all__ = [
    "Evidence",
    "GraphPath",
    "Heading",
    "Paragraph",
    "Provenance",
    "TextComponent",
]
