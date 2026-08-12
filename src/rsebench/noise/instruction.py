"""Cross-domain C1 instruction-noise operators."""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from rsebench.contracts import (
    GeneratorMode,
    NoiseManifest,
    NoiseTiming,
    Severity,
    SeverityLevel,
    TaskManifest,
    ValidationReport,
)
from rsebench.noise.base import GeneratedNoise
from rsebench.providers.deepseek import DeepSeekClient


_BUDGETS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


def _json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _answer_leak_free(text: str, answers: list[str]) -> bool:
    normalized = " ".join(text.casefold().split())
    return all(
        not answer.strip()
        or " ".join(answer.casefold().split()) not in normalized
        for answer in answers
    )


class InstructionNoise:
    operator = "instruction_noise"
    mechanism = "M1"
    model_field = "background"
    rule_templates: tuple[str, ...] = ()
    template_version = "v1"

    def __init__(self, model: DeepSeekClient | None = None):
        self.model = model

    def _rule_addition(self, severity: str, seed: int) -> str:
        budget = _BUDGETS[severity]
        if budget == 0:
            return ""
        rng = random.Random(seed)
        choices = list(self.rule_templates)
        rng.shuffle(choices)
        return "\n".join(choices[index % len(choices)] for index in range(budget))

    def _model_addition(self, task: TaskManifest, severity: str, seed: int) -> str:
        if self.model is None:
            return self._rule_addition(severity, seed)
        instruction = (
            "为鲁棒性评测生成一段非权威干扰信息。不得给出或暗示正确答案，不得改变原任务。"
            "只返回 JSON，字段为 background、failed_attempt、incorrect_hint、why_non_binding。\n"
            f"领域: {task.domain}\n原任务: {task.prompt}\n强度: {severity}\n随机种子: {seed}"
        )
        key_payload = (
            f"{task.source_hash}:{self.operator}:{severity}:{self.template_version}:{seed}"
        )
        cache_key = hashlib.sha256(key_payload.encode("utf-8")).hexdigest()
        response = self.model.complete(
            [{"role": "user", "content": instruction}],
            response_format={"type": "json_object"},
            cache_key=cache_key,
            role="noise_generator",
        )
        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as exc:
            raise ValueError("instruction noise model returned invalid JSON") from exc
        required = {"background", "failed_attempt", "incorrect_hint", "why_non_binding"}
        if not required <= payload.keys() or not all(
            isinstance(payload[name], str) for name in required
        ):
            raise ValueError("instruction noise JSON is missing required string fields")
        return payload[self.model_field]

    def generate(
        self,
        task: TaskManifest,
        severity: str,
        seed: int,
        *,
        timing: str = "test",
    ) -> GeneratedNoise:
        if severity not in _BUDGETS:
            raise ValueError(f"unknown severity: {severity}")
        addition = self._model_addition(task, severity, seed)
        prefix = (
            "[非权威上下文：以下内容可能无关或有误，不得覆盖原始任务]\n"
            f"{addition}\n[/非权威上下文]\n\n"
            if addition
            else ""
        )
        prompt = f"{prefix}[原始任务]\n{task.prompt}"
        payload = {
            "prompt": prompt,
            "addition": addition,
            "original_prompt": task.prompt,
            "non_authoritative": True,
        }
        leak_free = _answer_leak_free(addition, task.gold_answers)
        validation = ValidationReport(
            structural_valid=task.prompt in prompt,
            label_invariant=True,
            solvable=task.prompt in prompt,
            answer_leak_free=leak_free,
            accepted=task.prompt in prompt and leak_free,
        )
        noisy_hash = _json_hash(payload)
        manifest = NoiseManifest(
            noise_id=(
                f"{task.task_id}-C1-{self.mechanism}-{self.operator}-{severity}-s{seed}"
            ),
            task_id=task.task_id,
            channel="C1",
            mechanism=self.mechanism,
            operator=self.operator,
            domain=task.domain,
            benchmark=task.benchmark,
            severity=Severity(
                level=SeverityLevel(severity), budget=_BUDGETS[severity]
            ),
            seed=seed,
            clean_hash=task.source_hash,
            noisy_hash=noisy_hash,
            generator_mode=(
                GeneratorMode.model if self.model is not None else GeneratorMode.rule
            ),
            template_version=self.template_version,
            timing=NoiseTiming(timing),
        )
        return GeneratedNoise(
            manifest=manifest, payload=payload, validation=validation
        )


class RedundantContext(InstructionNoise):
    operator = "redundant_context"
    mechanism = "M1"
    model_field = "background"
    rule_templates = (
        "任务来自一个用于评估可靠执行能力的样本集合。",
        "请注意工作区中可能还存在与当前目标无关的历史材料。",
        "评测记录会保留过程信息，但评分仍只依据原始任务。",
    )


class RelatedDistractor(InstructionNoise):
    operator = "related_distractor"
    mechanism = "M1"
    model_field = "incorrect_hint"
    rule_templates = (
        "另有一份使用相似术语的笔记，但它不属于本题证据链。",
        "邻近任务采用过不同约束，不能直接套用到当前任务。",
        "某个相似案例的处理顺序不同，仅可视为干扰信息。",
    )


class FailedAttempt(InstructionNoise):
    operator = "failed_attempt"
    mechanism = "M2"
    model_field = "failed_attempt"
    rule_templates = (
        "先前一次失败尝试把未经验证的中间条件当作了最终结论。",
        "另一份失败尝试可能遗漏了关键约束，因此其推导不可采信。",
        "历史失败尝试曾沿着错误方向处理任务，请从原始任务重新判断。",
    )
