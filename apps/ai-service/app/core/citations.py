import re
from collections.abc import Sequence
from urllib.parse import quote

from app.core.schemas import SourceCitation
from app.core.telemetry import trace_method
from app.models.gateway import ModelGatewayError

SOURCE_MARKER = re.compile(r"\[source:([a-z0-9][a-z0-9-]{2,127})\]")
MALFORMED_SOURCE_MARKER = re.compile(r"\[\s*source\s*:", re.IGNORECASE)
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
        "markers, source labels, URLs, or links. Ordinary brackets in examples are allowed. "
        "Never copy placeholder IDs from examples."
    )


@trace_method
def validate_citations(text: str, sources: Sequence[SourceCitation]) -> None:
    approved = {source.source_id for source in sources}
    markers = SOURCE_MARKER.findall(text)
    remaining = SOURCE_MARKER.sub("", text)
    if MODEL_LINK.search(text) or MALFORMED_SOURCE_MARKER.search(remaining) or (
        not set(markers).issubset(approved)
    ):
        raise ModelGatewayError(
            "Generated content contained an unapproved citation.",
            code="UNAPPROVED_CITATION",
            component="citation_validation",
        )


def normalize_citation_markers(text: str, sources: Sequence[SourceCitation]) -> str:
    """Accept old citation syntax only when its ID is actually carried evidence.

    An ordinary bracket such as [food-budget] is not a citation declaration.
    Explicit [source:...] tokens remain strict even when the ID is unknown.
    """
    for source in sources:
        text = text.replace(f"[{source.source_id}]", f"[source:{source.source_id}]")
    return text


@trace_method
def render_citations(text: str, sources: Sequence[SourceCitation], locale: object = "en") -> str:
    text = normalize_citation_markers(text, sources)
    validate_citations(text, sources)
    approved = {source.source_id: source for source in sources}

    def reference(match: re.Match) -> str:
        source = approved[match[1]]
        label = re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", " ".join(source.title.split()))
        reference = f"[{label}]({quote(source.canonical_url, safe=':/?#=&%')})"
        # The Sources panel and response metadata carry filename/version/kind.
        # Keep citations readable when several claims use the same document.
        return reference

    return SOURCE_MARKER.sub(
        reference,
        text,
    )


def compact_evidence(data: dict) -> dict:
    """Keep full cited passages in review input; audit keeps all retrieval evidence."""
    result = dict(data)
    for field, keys in (
        ("contexts", ("source_id", "text")),
        ("sources", ("source_id", "title", "issuing_organization", "published_at",
                     "document_version", "review_due_at", "content_kind")),
    ):
        if field in data:
            compacted = [
                {key: item[key] for key in keys if key in item} for item in data[field]
                # Before generation all evidence is eligible. Once citations are
                # selected, unrelated passages cannot support the draft's claims.
                if "cited_source_ids" not in data
                or item["source_id"] in data["cited_source_ids"]
            ]
            # Shared capabilities can repeat the very same accepted passage.
            # Remove only exact duplicates, retaining distinct quotes from one
            # source and every critical qualification in their complete text.
            result[field] = []
            for item in compacted:
                if item not in result[field]:
                    result[field].append(item)
    if "subquestion_coverage" in data:
        coverage = []
        for question in data["subquestion_coverage"]:
            supports = []
            for original in question.get("supporting_passages", []):
                support = dict(original)
                text = support.get("quote", "")
                if support.get("evidence_field", "text") == "text" and len(text) >= 4:
                    for index, context in enumerate(result.get("contexts", [])):
                        if support.get("source_id") == context.get("source_id") and text in context.get("text", ""):
                            start = context["text"].index(text)
                            support.pop("quote")
                            support["quote_ref"] = {"context_index": index, "start": start, "end": start + len(text)}
                            break
                supports.append(support)
            coverage.append({**question, "supporting_passages": supports})
        result["subquestion_coverage"] = coverage
    return result
