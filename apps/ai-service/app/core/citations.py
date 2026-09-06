import re
from collections.abc import Sequence
from urllib.parse import quote

from app.core.schemas import SourceCitation
from app.models.gateway import ModelGatewayError

SOURCE_MARKER = re.compile(r"\[(?:source:)?([a-z0-9][a-z0-9-]{2,127})\]")
MODEL_LINK = re.compile(r"://|\bwww\.|\]\s*\(|<\s*a\b|\b(?:href|src)\s*=", re.IGNORECASE)


def validate_citations(text: str, sources: Sequence[SourceCitation]) -> None:
    approved = {source.source_id for source in sources}
    markers = SOURCE_MARKER.findall(text)
    remaining = SOURCE_MARKER.sub("", text)
    if MODEL_LINK.search(text) or "[" in remaining or "]" in remaining or (
        not set(markers).issubset(approved)
    ):
        raise ModelGatewayError(
            "Generated content contained an unapproved citation.",
            code="UNAPPROVED_CITATION",
            component="citation_validation",
        )


def render_citations(text: str, sources: Sequence[SourceCitation]) -> str:
    validate_citations(text, sources)
    approved = {source.source_id: source for source in sources}
    return SOURCE_MARKER.sub(
        lambda match: f"[{match[1]}]({quote(approved[match[1]].canonical_url, safe=':/?#=&%')})",
        text,
    )
