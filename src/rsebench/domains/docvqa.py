"""Answer-safe DocVQA image noise with explicit applicability handling."""

from __future__ import annotations

import random
import re
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from rsebench.contracts import ValidationReport


class Box(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x0: int = Field(ge=0)
    y0: int = Field(ge=0)
    x1: int = Field(gt=0)
    y1: int = Field(gt=0)

    def intersects(self, other: "Box") -> bool:
        return not (
            self.x1 <= other.x0
            or other.x1 <= self.x0
            or self.y1 <= other.y0
            or other.y1 <= self.y0
        )


class OCRToken(BaseModel):
    text: str
    box: Box


class DocVQATask(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    task_id: str
    question: str
    answers: list[str] = Field(min_length=1)
    image_path: Path
    answer_boxes: list[Box] = Field(default_factory=list)


class DocVQANoiseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    output_path: Path
    severity: str
    seed: int
    added_boxes: list[Box] = Field(default_factory=list)
    applicable: bool = True
    reason: str | None = None


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def locate_answer_regions(
    tokens: list[OCRToken], answers: list[str]
) -> list[Box]:
    token_words = [_words(token.text) for token in tokens]
    if any(len(words) != 1 for words in token_words):
        # OCR engines sometimes combine words; split-token alignment is not
        # safe enough for geometric protection, so defer the sample.
        return []
    flattened = [words[0] for words in token_words]
    found: list[Box] = []
    for answer in answers:
        target = _words(answer)
        if not target:
            continue
        for start in range(0, len(flattened) - len(target) + 1):
            if flattened[start : start + len(target)] != target:
                continue
            matched = [token.box for token in tokens[start : start + len(target)]]
            box = Box(
                x0=min(item.x0 for item in matched),
                y0=min(item.y0 for item in matched),
                x1=max(item.x1 for item in matched),
                y1=max(item.y1 for item in matched),
            )
            if box not in found:
                found.append(box)
    return found


def _margin_candidates(width: int, height: int) -> list[Box]:
    box_width = max(24, min(80, width // 3))
    box_height = max(14, min(28, height // 10))
    pad = max(2, min(width, height) // 50)
    return [
        Box(x0=pad, y0=pad, x1=pad + box_width, y1=pad + box_height),
        Box(
            x0=width - pad - box_width,
            y0=pad,
            x1=width - pad,
            y1=pad + box_height,
        ),
        Box(
            x0=pad,
            y0=height - pad - box_height,
            x1=pad + box_width,
            y1=height - pad,
        ),
        Box(
            x0=width - pad - box_width,
            y0=height - pad - box_height,
            x1=width - pad,
            y1=height - pad,
        ),
    ]


def inject_margin_clutter(
    task: DocVQATask,
    output_path: Path | str,
    *,
    severity: str,
    seed: int,
) -> DocVQANoiseResult:
    if severity not in {"L1", "L2", "L3"}:
        raise ValueError(f"unsupported severity: {severity}")
    output = Path(output_path)
    if not task.answer_boxes:
        return DocVQANoiseResult(
            output_path=output,
            severity=severity,
            seed=seed,
            applicable=False,
            reason="answer_region_unavailable",
        )
    with Image.open(task.image_path) as source:
        image = source.convert("RGB")
    candidates = _margin_candidates(*image.size)
    safe = [
        candidate
        for candidate in candidates
        if all(not candidate.intersects(answer) for answer in task.answer_boxes)
    ]
    random.Random(seed).shuffle(safe)
    budget = {"L1": 1, "L2": 2, "L3": 3}[severity]
    added = safe[:budget]
    if not added:
        return DocVQANoiseResult(
            output_path=output,
            severity=severity,
            seed=seed,
            applicable=False,
            reason="no_safe_margin",
        )
    draw = ImageDraw.Draw(image)
    for index, box in enumerate(added, start=1):
        draw.rectangle(
            (box.x0, box.y0, box.x1, box.y1),
            fill="#eeeeee",
            outline="#777777",
            width=1,
        )
        draw.text((box.x0 + 2, box.y0 + 2), f"DRAFT {index}", fill="#555555")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return DocVQANoiseResult(
        output_path=output,
        severity=severity,
        seed=seed,
        added_boxes=added,
    )


def validate_docvqa_noise(
    task: DocVQATask, result: DocVQANoiseResult
) -> ValidationReport:
    if not result.applicable:
        return ValidationReport(
            structural_valid=True,
            label_invariant=True,
            solvable=True,
            answer_leak_free=True,
            accepted=False,
            applicable=False,
            messages=[result.reason or "not_applicable"],
        )
    non_intersection = all(
        not added.intersects(answer)
        for added in result.added_boxes
        for answer in task.answer_boxes
    )
    try:
        with Image.open(task.image_path) as clean, Image.open(result.output_path) as noisy:
            structural = clean.size == noisy.size and bool(result.added_boxes)
    except Exception:
        structural = False
    accepted = structural and non_intersection
    return ValidationReport(
        structural_valid=structural,
        label_invariant=non_intersection,
        solvable=non_intersection,
        answer_leak_free=True,
        accepted=accepted,
        checks={"added_box_count": len(result.added_boxes)},
        messages=[] if accepted else ["image structure or answer mask gate failed"],
    )
