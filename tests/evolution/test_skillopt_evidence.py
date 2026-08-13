from __future__ import annotations

from rsebench.evidence import HookContext, RuntimeNoiseSpec
from rsebench.evolution.skillopt_evidence import (
    apply_skillopt_evidence_from_env,
    mutate_skillopt_conversation,
    mutate_skillopt_feedback_item,
)


def context(tmp_path, *, benchmark: str, domain: str, arm: str = "noisy") -> HookContext:
    return HookContext(
        task_id="task-1",
        benchmark=benchmark,
        domain=domain,
        method="skillopt",
        arm=arm,
        run_dir=tmp_path,
    )


def spreadsheet_conversation() -> list[dict[str, object]]:
    return [
        {
            "role": "assistant",
            "content": (
                "```python\nws['Summary!B2'] = 10\n"
                "ws['Archive!B2'] = 9\nwb.save(OUTPUT_PATH)\n```"
            ),
        },
        {
            "role": "system",
            "content": (
                "[POST-EXECUTION VERIFICATION]\n"
                "value@Summary!B2: got=10 expected=11"
            ),
        },
    ]


def test_identity_path_returns_same_conversation_object(tmp_path) -> None:
    conversation = spreadsheet_conversation()

    output = mutate_skillopt_conversation(
        conversation,
        spec=None,
        context=context(
            tmp_path, benchmark="spreadsheetbench_verified", domain="spreadsheet", arm="clean"
        ),
    )

    assert output is conversation


def test_n3_omits_workbook_write_before_reflection(tmp_path) -> None:
    conversation = spreadsheet_conversation()
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="spreadsheet_n3_omit_workbook_edit",
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["workbook_write"]},
    )

    output = mutate_skillopt_conversation(
        conversation,
        spec=spec,
        context=context(tmp_path, benchmark=spec.benchmark, domain=spec.domain),
    )

    assert len(output) == 1
    assert output[0]["role"] == "system"
    audit = tmp_path / "mutation_audit/noisy/task-1/N3/audit.json"
    assert audit.exists()


def test_officeqa_n3_omits_oracle_read_tool_event(tmp_path) -> None:
    conversation = [
        {"role": "user", "content": "Question and oracle context"},
        {
            "type": "tool_call",
            "cmd": "read(path='/docs/treasury_2024.txt')",
            "obs": "table text",
        },
        {"type": "message", "content": "<answer>42</answer>"},
    ]
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="officeqa_n3_omit_oracle_source",
        benchmark="officeqa_full",
        domain="document",
        seed=7,
        selector="oracle_resource_open",
        selector_parameters={"oracle_resource_refs": ["treasury_2024.txt"]},
    )

    output = mutate_skillopt_conversation(
        conversation,
        spec=spec,
        context=context(tmp_path, benchmark=spec.benchmark, domain=spec.domain),
    )

    assert [row.get("type") for row in output] == [None, "message"]


def test_officeqa_env_hook_derives_oracle_refs_from_native_item(
    tmp_path, monkeypatch
) -> None:
    conversation = [
        {
            "type": "tool_call",
            "cmd": "read(path='/docs/treasury_2024.txt')",
            "obs": "oracle table text",
        },
        {"type": "message", "content": "<answer>42</answer>"},
    ]
    spec_path = tmp_path / "n3.json"
    spec_path.write_text(
        RuntimeNoiseSpec(
            stage="N3",
            operator="officeqa_n3_omit_oracle_source",
            benchmark="officeqa_full",
            domain="document",
            seed=7,
            selector="oracle_resource_open",
            selector_parameters={"event_tags": ["source_open", "source_read"]},
        ).model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setenv("RSEBENCH_EVIDENCE_SPEC", str(spec_path))
    monkeypatch.setenv("RSEBENCH_EVIDENCE_AUDIT_ROOT", str(tmp_path / "run"))
    monkeypatch.setenv("RSEBENCH_EVIDENCE_ARM", "noisy")

    output, native_item = apply_skillopt_evidence_from_env(
        conversation,
        {
            "id": "task-1",
            "source_files": ["treasury_2024.txt"],
            "question": "What is the reported value?",
        },
    )

    assert [row.get("type") for row in output] == ["message"]
    assert native_item["source_files"] == ["treasury_2024.txt"]


def test_n4_changes_analyst_fail_reason_but_not_scores_or_conversation(tmp_path) -> None:
    conversation = spreadsheet_conversation()
    item = {
        "id": "task-1",
        "hard": 0,
        "soft": 0.25,
        "fail_reason": "value@Summary!B2 is incorrect",
    }
    spec = RuntimeNoiseSpec(
        stage="N4",
        operator="spreadsheet_n4_replace_blamed_range",
        benchmark="spreadsheetbench_verified",
        domain="spreadsheet",
        seed=7,
        selector="same_shape_decoy_resource",
        selector_parameters={
            "replacement_diagnosis": "value@Archive!B2 is incorrect"
        },
    )

    output = mutate_skillopt_feedback_item(
        item,
        conversation,
        spec=spec,
        context=context(tmp_path, benchmark=spec.benchmark, domain=spec.domain),
    )

    assert output["fail_reason"] == "value@Archive!B2 is incorrect"
    assert output["hard"] == item["hard"]
    assert output["soft"] == item["soft"]
    assert conversation == spreadsheet_conversation()
    assert item["fail_reason"] == "value@Summary!B2 is incorrect"
