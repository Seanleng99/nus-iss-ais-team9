from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from threading import Event, Lock

import pytest

from app.rag import request_cache
from app.rag.request_cache import (
    RequestScopedEducationRetriever,
)


class CountingRetriever:
    expected_corpus_version = "investment-education-sg@test-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.lock = Lock()

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, object]]:
        with self.lock:
            self.calls.append((query, top_k))
            call_number = len(self.calls)
        return [{"query": query, "top_k": top_k, "call": call_number}]


def _run_in_copied_contexts(
    retriever: RequestScopedEducationRetriever,
    query: str,
    count: int,
) -> list[list[dict[str, object]]]:
    contexts = [copy_context() for _ in range(count)]
    with ThreadPoolExecutor(max_workers=count) as executor:
        futures = [
            executor.submit(context.run, retriever.retrieve, query)
            for context in contexts
        ]
        return [future.result() for future in futures]


def test_identical_queries_share_one_inflight_retrieval_across_contexts() -> None:
    delegate = CountingRetriever()
    retriever = RequestScopedEducationRetriever(delegate)
    token = retriever.begin_request()
    try:
        results = _run_in_copied_contexts(retriever, "same query", 8)
    finally:
        retriever.end_request(token)

    assert delegate.calls == [("same query", 3)]
    assert results == [[{"query": "same query", "top_k": 3, "call": 1}]] * 8
    assert len({id(result) for result in results}) == 8


def test_top_k_is_part_of_cache_key() -> None:
    delegate = CountingRetriever()
    retriever = RequestScopedEducationRetriever(delegate)
    token = retriever.begin_request()
    try:
        first = retriever.retrieve("same query", top_k=3)
        second = retriever.retrieve("same query", top_k=5)
    finally:
        retriever.end_request(token)

    assert delegate.calls == [("same query", 3), ("same query", 5)]
    assert first[0]["top_k"] == 3
    assert second[0]["top_k"] == 5


def test_request_end_and_outside_scope_do_not_reuse_results() -> None:
    delegate = CountingRetriever()
    retriever = RequestScopedEducationRetriever(delegate)

    first_token = retriever.begin_request()
    try:
        first = retriever.retrieve("same query")
    finally:
        retriever.end_request(first_token)

    second_token = retriever.begin_request()
    try:
        second = retriever.retrieve("same query")
    finally:
        retriever.end_request(second_token)

    outside_first = retriever.retrieve("same query")
    outside_second = retriever.retrieve("same query")

    assert len(delegate.calls) == 4
    assert first[0]["call"] == 1
    assert second[0]["call"] == 2
    assert outside_first[0]["call"] == 3
    assert outside_second[0]["call"] == 4


def test_wrappers_keep_request_state_isolated() -> None:
    first_delegate = CountingRetriever()
    second_delegate = CountingRetriever()
    first_retriever = RequestScopedEducationRetriever(first_delegate)
    second_retriever = RequestScopedEducationRetriever(second_delegate)
    first_token = first_retriever.begin_request()
    second_token = second_retriever.begin_request()
    try:
        first_retriever.retrieve("same query")
        first_retriever.retrieve("same query")
        second_retriever.retrieve("same query")
        second_retriever.retrieve("same query")
    finally:
        second_retriever.end_request(second_token)
        first_retriever.end_request(first_token)

    assert first_delegate.calls == [("same query", 3)]
    assert second_delegate.calls == [("same query", 3)]


class RecoveringRetriever:
    expected_corpus_version = "investment-education-sg@test-v1"

    def __init__(self, wait_before_failure: Event | None = None) -> None:
        self.calls = 0
        self.lock = Lock()
        self.wait_before_failure = wait_before_failure

    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        del query, top_k
        with self.lock:
            self.calls += 1
            call_number = self.calls
        if call_number == 1:
            if self.wait_before_failure is not None:
                assert self.wait_before_failure.wait(timeout=5)
            raise RuntimeError("retrieval unavailable")
        return [f"success-{call_number}"]


def test_failure_is_shared_without_hanging_and_next_request_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_attached = Event()

    class ObservedFuture(Future):
        def result(self, timeout: float | None = None):
            waiter_attached.set()
            return super().result(timeout)

    monkeypatch.setattr(request_cache, "Future", ObservedFuture)
    delegate = RecoveringRetriever(wait_before_failure=waiter_attached)
    retriever = RequestScopedEducationRetriever(delegate)
    token = retriever.begin_request()
    try:
        contexts = [copy_context() for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(context.run, retriever.retrieve, "failing query")
                for context in contexts
            ]
            errors = []
            for future in futures:
                with pytest.raises(RuntimeError, match="retrieval unavailable") as raised:
                    future.result()
                errors.append(raised.value)
        assert retriever.retrieve("failing query") == ["success-2"]
    finally:
        retriever.end_request(token)

    next_token = retriever.begin_request()
    try:
        assert retriever.retrieve("failing query") == ["success-3"]
    finally:
        retriever.end_request(next_token)

    assert delegate.calls == 3
    assert errors[0] is errors[1]


def test_expected_corpus_version_delegates_without_inventing_provenance() -> None:
    class CorpusVersionOnlyRetriever:
        corpus_version = "custom-corpus"

        def retrieve(self, query: str, top_k: int = 3) -> list[object]:
            del query, top_k
            return []

    class BareRetriever:
        def retrieve(self, query: str, top_k: int = 3) -> list[object]:
            del query, top_k
            return []

    assert (
        RequestScopedEducationRetriever(CorpusVersionOnlyRetriever()).expected_corpus_version
        == "custom-corpus"
    )
    assert (
        RequestScopedEducationRetriever(BareRetriever()).expected_corpus_version
        is None
    )
