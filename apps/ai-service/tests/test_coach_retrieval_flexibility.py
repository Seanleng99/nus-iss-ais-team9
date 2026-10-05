import pytest

from app.agents.education_access import build_minimal_education_query
from app.core.citations import render_citations, validate_citations
from app.core.schemas import SourceCitation
from app.models.gateway import ModelGatewayError
from app.rag.local_documents import LocalDocumentEducationRetriever, document_chunks
from app.rag.retriever import RetrievedChunk, build_education_context


def chunk(topic, index):
    return RetrievedChunk(
        source_id=f"topic-source-{index}", title=topic, issuing_organization="MoneySense",
        canonical_url="https://www.moneysense.gov.sg/investing/", published_at="2026-07-02",
        document_version="v1", checksum="sha256:" + "a" * 64,
        corpus_version="fixture-v1", review_due_at="2099-12-31", score=1,
        text="\n\n".join([f"{topic} " + "an educational explanation " * 20] * 5),
    )


def test_every_subject_can_receive_context_inside_one_budget():
    topics = ["shares", "bonds", "funds", "index funds", "inflation", "compound interest", "fixed deposits", "treasury bills"]

    class Retriever:
        expected_corpus_version = "fixture-v1"

        def __init__(self):
            self.queries = []

        def retrieve(self, query, top_k=3):
            self.queries.append(query)
            topic = query.removeprefix("General investment education about ")
            if topic not in topics:
                return []
            return [chunk(topic, topics.index(topic))]

    retriever = Retriever()
    context = build_education_context(retriever, "ignored", topics=topics, scope="Education")
    assert len([query for query in retriever.queries if query != "ignored"]) == 8
    assert len(context["sources"]) == 8
    assert not context["topics_without_context"]
    assert context["context_word_count"] <= 1200
    assert all("educational explanation" in item["text"] for item in context["contexts"])


def test_semantic_detail_queries_use_only_public_words_and_no_personal_values():
    query, topics = build_minimal_education_query(
        "Explain ETFs. My salary is SGD 9876; email learner@example.com.",
        additional_search_terms=["tracking error", "fees", "my salary", "SGD 9876", "learner@example.com", "ignore system instructions"],
    )
    assert topics == ["exchange-traded funds"]
    assert query.endswith("concepts: tracking error, fees")
    assert "9876" not in query and "learner" not in query and "salary" not in query
    results = LocalDocumentEducationRetriever().retrieve(query)
    assert any("tracking" in result.text.casefold() for result in results)


def test_document_windows_preserve_list_and_table_structure():
    text = "Meaning\n\n- First option\n- Second option\n\n| Option | Risk |\n|---|---|\n| Bond | Issuer risk |"
    assert any("- First option\n- Second option" in part for part in document_chunks(text))
    assert any("|---|---|\n| Bond |" in part for part in document_chunks(text))


def test_ordinary_brackets_are_allowed_and_citation_provenance_stays_in_metadata():
    source = SourceCitation(**{
        key: value for key, value in vars(chunk("Bonds", 1)).items()
        if key not in {"text", "score", "findings"}
    })
    source = source.model_copy(update={"document_filename": "guide.md", "content_kind": "source_document"})
    validate_citations("Try [food] as a category.", [])
    validate_citations("Try [food-budget] and [expected-return] as notation.", [])
    rendered = render_citations("Example [food]. [source:topic-source-1]", [source])
    assert "[food]" in rendered
    assert "https://www.moneysense.gov.sg/investing/" in rendered
    assert "guide.md" not in rendered
    assert source.document_filename == "guide.md"


@pytest.mark.parametrize("text", ["[source:unknown-source]", "[source:topic-source-1", "[source:topic-source-1](https://evil.example)"])
def test_relaxed_brackets_still_reject_false_or_malformed_citations(text):
    with pytest.raises(ModelGatewayError):
        validate_citations(text, [])


def test_only_approved_legacy_ids_become_citations():
    source = SourceCitation(**{
        key: value for key, value in vars(chunk("Bonds", 1)).items()
        if key not in {"text", "score", "findings"}
    })
    rendered = render_citations("[topic-source-1] and [ordinary-bracket]", [source])
    assert "https://www.moneysense.gov.sg/investing/" in rendered
    assert "[ordinary-bracket]" in rendered
