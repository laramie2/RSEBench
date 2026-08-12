from pathlib import Path

from PIL import Image

from rsebench.domains.docvqa import (
    Box,
    DocVQATask,
    OCRToken,
    inject_margin_clutter,
    locate_answer_regions,
    validate_docvqa_noise,
)


def _task(tmp_path: Path, boxes: list[Box]) -> DocVQATask:
    image = tmp_path / "clean.png"
    Image.new("RGB", (200, 200), "white").save(image)
    return DocVQATask(
        task_id="doc-1",
        question="What is the total?",
        answers=["forty two"],
        image_path=image,
        answer_boxes=boxes,
    )


def test_margin_clutter_never_intersects_answer_boxes(tmp_path: Path):
    task = _task(tmp_path, [Box(x0=70, y0=70, x1=130, y1=100)])
    result = inject_margin_clutter(
        task, tmp_path / "noisy.png", severity="L1", seed=5
    )
    assert all(
        not added.intersects(answer)
        for added in result.added_boxes
        for answer in task.answer_boxes
    )
    assert validate_docvqa_noise(task, result).accepted


def test_missing_answer_localization_is_not_applicable(tmp_path: Path):
    task = _task(tmp_path, [])
    result = inject_margin_clutter(
        task, tmp_path / "unused.png", severity="L1", seed=5
    )
    assert not result.applicable
    assert not result.output_path.exists()
    report = validate_docvqa_noise(task, result)
    assert not report.applicable
    assert not report.accepted


def test_answer_region_locator_matches_contiguous_ocr_tokens():
    tokens = [
        OCRToken(text="Total", box=Box(x0=5, y0=5, x1=40, y1=20)),
        OCRToken(text="forty", box=Box(x0=45, y0=5, x1=80, y1=20)),
        OCRToken(text="two", box=Box(x0=85, y0=5, x1=105, y1=20)),
    ]
    boxes = locate_answer_regions(tokens, ["forty two"])
    assert boxes == [Box(x0=45, y0=5, x1=105, y1=20)]
