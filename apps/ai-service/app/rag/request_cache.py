from concurrent.futures import Future
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Lock

from app.rag.retriever import EducationRetriever, RetrievedChunk


@dataclass
class _RequestState:
    futures: dict[tuple[str, int], Future[list[RetrievedChunk]]] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)


class RequestScopedEducationRetriever:
    def __init__(self, delegate: EducationRetriever) -> None:
        self.delegate = delegate
        self._state: ContextVar[_RequestState | None] = ContextVar(
            f"education_request_state_{id(self)}", default=None
        )

    def begin_request(self) -> Token[_RequestState | None]:
        return self._state.set(_RequestState())

    def end_request(self, token: Token[_RequestState | None]) -> None:
        self._state.reset(token)

    @property
    def expected_corpus_version(self) -> str | None:
        return getattr(
            self.delegate,
            "expected_corpus_version",
            getattr(self.delegate, "corpus_version", None),
        )

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        state = self._state.get()
        if state is None:
            return list(self.delegate.retrieve(query, top_k))

        key = (query, top_k)
        with state.lock:
            future = state.futures.get(key)
            owner = future is None
            if owner:
                future = Future()
                state.futures[key] = future

        if owner:
            try:
                future.set_result(list(self.delegate.retrieve(query, top_k)))
            except Exception as error:
                with state.lock:
                    if state.futures.get(key) is future:
                        del state.futures[key]
                future.set_exception(error)
                raise

        return list(future.result())
