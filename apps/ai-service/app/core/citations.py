import re
from collections.abc import Sequence
from urllib.parse import quote

from app.core.schemas import SourceCitation
from app.core.telemetry import trace_method
from app.models.gateway import ModelGatewayError

SOURCE_MARKER = re.compile(r"\[(?:source:)?([a-z0-9][a-z0-9-]{2,127})\]")
MODEL_LINK = re.compile(r"://|\bwww\.|\]\s*\(|<\s*a\b|\b(?:href|src)\s*=", re.IGNORECASE)


def citation_contract(sources: Sequence[SourceCitation]) -> str:
    if sources:
        return (
            "\nCitation contract for THIS request: the only approved source IDs are "
            + ", ".join(source.source_id for source in sources)
            + ". Cite only actual supporting IDs from this list. "
            "Never copy placeholder IDs from examples. Do not generate URLs or links."
        )
    return (
        "\nCitation contract for THIS request: there are NO approved sources. "
        "Preserve the supplied calculations and explanations without citation "
        "markers, source labels, URLs, links, or square brackets. "
        "Never copy placeholder IDs from examples."
    )


@trace_method
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


@trace_method
def render_citations(text: str, sources: Sequence[SourceCitation]) -> str:
    validate_citations(text, sources)
    approved = {source.source_id: source for source in sources}

    def reference(match: re.Match) -> str:
        source = approved[match[1]]
        label = re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", " ".join(source.title.split()))
        return f"[{label}]({quote(source.canonical_url, safe=':/?#=&%')})"

    return SOURCE_MARKER.sub(
        reference,
        text,
    )


def compact_evidence(data: dict) -> dict:
    """Keep full passages and relevant metadata in model input; audit keeps full provenance."""
    result = dict(data)
    for field, keys in (
        ("contexts", ("source_id", "text")),
        ("sources", ("source_id", "title", "issuing_organization", "published_at",
                     "document_version", "review_due_at")),
    ):
        if field in data:
            result[field] = [
                {key: item[key] for key in keys if key in item} for item in data[field]
            ]
    return result
