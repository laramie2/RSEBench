"""OfficeQA retrieval-fixture noise with gold-presence hard gates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from rsebench.contracts import ValidationReport


class OfficeQATask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    question: str
    answers: list[str] = Field(min_length=1)
    gold_document_id: str
    source_document_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CorpusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    text: str
    path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    document_id: str
    text: str = ""
    score: float = 0.0
    is_gold: bool = False


class RetrievalFixture(BaseModel):
    task_id: str
    results: list[RetrievalResult]
    expected_gold_rank: int = Field(ge=1)
    expected_gold_document_ids: list[str] = Field(default_factory=list)
    fixture_hash: str


@dataclass(frozen=True)
class DecoyIndex:
    documents: tuple[CorpusDocument, ...]
    tokens_by_id: dict[str, frozenset[str]]
    content_fingerprints: dict[str, str]
    vocabulary: frozenset[str] | None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _normalized(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", text.casefold()))


def build_question_vocabulary(questions: Iterable[str]) -> set[str]:
    vocabulary: set[str] = set()
    for question in questions:
        vocabulary.update(_tokens(question))
    return vocabulary


def _contextual_answer_leak(question: str, text: str, answers: list[str]) -> bool:
    """Reject an answer only when it appears in a query-related local span.

    Treasury documents contain many short numeric values, so a document-wide
    substring rule would incorrectly reject nearly every useful decoy.
    """
    query_tokens = {
        token
        for token in _tokens(question)
        if token not in {"what", "were", "was", "the", "of", "in", "for", "a", "an"}
    }
    normalized_answers = {
        normalized for answer in answers if (normalized := _normalized(answer))
    }
    for span in re.split(r"[\n.!?;]+", text):
        if len(query_tokens & _tokens(span)) < 2:
            continue
        normalized_span = _normalized(span)
        if any(answer in normalized_span for answer in normalized_answers):
            return True
    return False


def build_corpus_index(root: Path | str) -> list[CorpusDocument]:
    corpus_root = Path(root)
    documents: list[CorpusDocument] = []
    for path in sorted(corpus_root.rglob("*.txt")):
        documents.append(
            CorpusDocument(
                document_id=path.relative_to(corpus_root).as_posix(),
                text=path.read_text(encoding="utf-8", errors="replace"),
                path=str(path),
            )
        )
    return documents


def build_decoy_index(
    documents: list[CorpusDocument], *, vocabulary: set[str] | None = None
) -> DecoyIndex:
    selected_vocabulary = frozenset(vocabulary) if vocabulary is not None else None
    tokens_by_id: dict[str, frozenset[str]] = {}
    content_fingerprints: dict[str, str] = {}
    for document in documents:
        tokens = _tokens(document.text)
        if selected_vocabulary is not None:
            tokens &= selected_vocabulary
        tokens_by_id[document.document_id] = frozenset(tokens)
        content_fingerprints[document.document_id] = hashlib.sha256(
            _normalized(document.text).encode("utf-8")
        ).hexdigest()
    return DecoyIndex(
        documents=tuple(documents),
        tokens_by_id=tokens_by_id,
        content_fingerprints=content_fingerprints,
        vocabulary=selected_vocabulary,
    )


def select_decoy_documents(
    task: OfficeQATask,
    documents: list[CorpusDocument],
    *,
    limit: int,
    index: DecoyIndex | None = None,
) -> list[CorpusDocument]:
    question_tokens = _tokens(task.question)
    search_index = index or build_decoy_index(
        documents, vocabulary=question_tokens
    )
    gold_ids = {task.gold_document_id, *task.source_document_ids}
    seen_text: set[str] = set()
    scored: list[tuple[float, str, CorpusDocument]] = []
    for document in search_index.documents:
        if document.document_id in gold_ids:
            continue
        fingerprint = search_index.content_fingerprints[document.document_id]
        if fingerprint in seen_text:
            continue
        seen_text.add(fingerprint)
        overlap = len(
            question_tokens & search_index.tokens_by_id[document.document_id]
        )
        if overlap == 0:
            continue
        score = overlap / max(1, len(question_tokens))
        scored.append((score, document.document_id, document))
    scored.sort(key=lambda row: (-row[0], row[1]))
    selected: list[CorpusDocument] = []
    for _, _, document in scored:
        if _contextual_answer_leak(task.question, document.text, task.answers):
            continue
        selected.append(document)
        if len(selected) == limit:
            break
    return selected


def build_rank_fixture(
    task: OfficeQATask,
    decoys: list[CorpusDocument | str],
    *,
    gold_rank: int,
) -> RetrievalFixture:
    if gold_rank < 1:
        raise ValueError("gold_rank must be positive")
    gold_document_ids = list(
        dict.fromkeys([task.gold_document_id, *task.source_document_ids])
    )
    normalized: list[CorpusDocument] = []
    seen: set[str] = set(gold_document_ids)
    for candidate in decoys:
        document = (
            candidate
            if isinstance(candidate, CorpusDocument)
            else CorpusDocument(document_id=str(candidate), text="")
        )
        if document.document_id not in seen:
            normalized.append(document)
            seen.add(document.document_id)
    if len(normalized) < gold_rank - 1:
        raise ValueError(
            f"gold rank {gold_rank} requires at least {gold_rank - 1} unique decoys"
        )
    results = [
        RetrievalResult(
            document_id=document.document_id,
            text=document.text,
            score=float(len(normalized) - index),
        )
        for index, document in enumerate(normalized)
    ]
    for offset, document_id in enumerate(gold_document_ids):
        results.insert(
            gold_rank - 1 + offset,
            RetrievalResult(
                document_id=document_id,
                is_gold=True,
                score=float(len(normalized) - gold_rank + 1 - offset),
            ),
        )
    payload = "\n".join(
        f"{index + 1}\t{result.document_id}\t{int(result.is_gold)}"
        for index, result in enumerate(results)
    )
    return RetrievalFixture(
        task_id=task.task_id,
        results=results,
        expected_gold_rank=gold_rank,
        expected_gold_document_ids=gold_document_ids,
        fixture_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def validate_officeqa_noise(
    task: OfficeQATask, fixture: RetrievalFixture
) -> ValidationReport:
    expected_gold_ids = fixture.expected_gold_document_ids or list(
        dict.fromkeys([task.gold_document_id, *task.source_document_ids])
    )
    gold_positions = [
        index + 1
        for index, result in enumerate(fixture.results)
        if result.document_id in expected_gold_ids
    ]
    gold_ids_in_order = [
        result.document_id
        for result in fixture.results
        if result.document_id in expected_gold_ids
    ]
    leaked = any(
        _contextual_answer_leak(task.question, result.text, task.answers)
        for result in fixture.results
        if result.document_id not in expected_gold_ids
    )
    expected_positions = list(
        range(
            fixture.expected_gold_rank,
            fixture.expected_gold_rank + len(expected_gold_ids),
        )
    )
    gold_once = (
        gold_positions == expected_positions
        and gold_ids_in_order == expected_gold_ids
        and all(
            sum(result.document_id == document_id for result in fixture.results) == 1
            for document_id in expected_gold_ids
        )
    )
    return ValidationReport(
        structural_valid=bool(fixture.results) and gold_once,
        label_invariant=gold_once,
        solvable=gold_once,
        answer_leak_free=not leaked,
        accepted=gold_once and not leaked,
        checks={
            "gold_rank": gold_positions[0] if gold_positions else -1,
            "gold_document_count": len(gold_ids_in_order),
            "result_count": len(fixture.results),
        },
        messages=[] if gold_once and not leaked else ["gold rank or leakage gate failed"],
    )
