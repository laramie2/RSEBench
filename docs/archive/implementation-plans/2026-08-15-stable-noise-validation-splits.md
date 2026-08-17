# Stable Noise Validation Split Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Select, clean-qualify, freeze, and locally commit one portable screening split plus one independent confirmation split for each of the four RSEBench domains without running N1–N4 noisy evolution.

**Architecture:** Add a focused rsebench.selection package for typed exposure, candidate, qualification, and release logic. Thin scripts materialize deterministic candidates, replay frozen clean artifacts through the existing executors, and freeze a content-addressed Git-ready bundle. Provider-active outputs remain under outputs/; only portable manifests, compact evidence, hashes, and resource locks enter Git.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, PyYAML, existing RSEBench clean runners/scheduler, SHA-256 canonical JSON identities.

**Approved design:** [stable split design](../design-specs/2026-08-15-stable-noise-validation-splits-design.md)

## Global Constraints

- Current scope ends after sample selection and local commit; do not run N1–N4 and do not push to GitHub.
- Benchmarks/baselines are SpreadsheetBench-Verified/SkillOpt, OfficeQA Full/SkillOpt, WebShop/SkillAdaptor, and SkillLearnBench/Self-Feedback.
- Provider identity is deepseek-v4-flash, temperature 0, thinking disabled; method seeds are exactly 20260813, 20260814, 20260815.
- Screening sizes are Spreadsheet 20/10/30, OfficeQA 12/12/20, WebShop 5/5/20, and four SkillLearn families with 2/1/2–3 per family.
- Confirmation sizes match screening and use four different SkillLearn families.
- SkillLearn screening families are organize-messy-files, offer-letter-generator, schedule-planning, and dependency-vulnerability-check; confirmation families are court-form-filling, earthquake-plate-calculation, dbscan-parameter-tuning, and travel-planning.
- Candidate 1 is current clean-v2; Candidate 2/3 replace train only and retain the fixed screening validation set.
- The three-candidate fallback applies to Spreadsheet, OfficeQA, and WebShop. SkillLearn keeps its one preregistered 2/1/remainder allocation because post-result family or instance substitution would violate the fixed-family rule; fewer than three clean-ready families blocks that domain.
- Candidate selection uses sequential stopping; the first pass wins and no test-score maximization is permitted.
- New Spreadsheet/OfficeQA/WebShop screening tests exclude historically score-observed tasks; confirmation excludes historically executed tasks.
- SkillLearn's documented development-screening exception does not relax confirmation-family isolation.
- Preflight, image-build, and dry-run artifacts remain `manifest_only` unless the artifact itself contains task execution or score evidence; the selection output subtree is excluded from its own exposure scan.
- JSON release files contain no absolute paths, worktree paths, credentials, or large unlicensed benchmark payloads.
- Existing unrelated working-tree edits belong to the user and are never staged with selection commits.

---

### Task 1: Finish the generic fixed-artifact replay foundation

**Files:**
- Modify: .gitignore
- Modify: src/rsebench/evolution/artifact_evaluation.py
- Create: scripts/replay_fixed_skillopt_artifacts.py
- Create: tests/evolution/test_repeated_artifact_evaluation.py
- Create: tests/validation/test_replay_fixed_skillopt_artifacts.py
- Create: docs/reports/2026-08-15-clean-v2-and-fixed-artifact-replay.md

**Interfaces:**
- Consumes: EvolutionExecutor.evaluate(skill_path, clean_test, output_dir, stage) -> EvaluationResult.
- Produces: evaluate_repeated_artifacts(...) -> RepeatedArtifactReplayResult and a resumable SkillOpt CLI used by selection qualification.

- [ ] **Step 1: Run the existing replay tests**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/evolution/test_repeated_artifact_evaluation.py \
  tests/validation/test_replay_fixed_skillopt_artifacts.py -q
~~~

Expected: all tests pass. If artifact_evaluation.py contains the same task-ID guard twice, retain exactly one copy.

- [ ] **Step 2: Verify the public interface used by later tasks**

The implementation must expose this exact signature:

~~~python
def evaluate_repeated_artifacts(
    *,
    executor: EvolutionExecutor,
    artifacts: dict[str, Path | str],
    reference_label: str,
    clean_test: list[TaskManifest],
    repeats: int,
    output_dir: Path | str,
    resume: bool = False,
) -> RepeatedArtifactReplayResult:
    """Evaluate immutable artifacts with cyclic rotation and paired deltas."""
~~~

RepeatedArtifactReplayResult retains task_manifest_hash, artifact_hashes, reference_label, repeat_count, per-artifact mean_delta_vs_reference, three-level timing inputs, and token usage.

- [ ] **Step 3: Run regression and lint checks**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/evolution/test_repeated_artifact_evaluation.py \
  tests/validation/test_replay_fixed_skillopt_artifacts.py \
  tests/evolution/test_artifact_evaluation.py -q
ruff check src/rsebench/evolution/artifact_evaluation.py \
  scripts/replay_fixed_skillopt_artifacts.py \
  tests/evolution/test_repeated_artifact_evaluation.py \
  tests/validation/test_replay_fixed_skillopt_artifacts.py
git diff --check
~~~

Expected: tests pass, Ruff prints All checks passed!, and diff check is silent.

- [ ] **Step 4: Commit only the replay foundation**

~~~bash
git add .gitignore \
  src/rsebench/evolution/artifact_evaluation.py \
  scripts/replay_fixed_skillopt_artifacts.py \
  tests/evolution/test_repeated_artifact_evaluation.py \
  tests/validation/test_replay_fixed_skillopt_artifacts.py \
  docs/reports/2026-08-15-clean-v2-and-fixed-artifact-replay.md
git commit -m "feat: add repeated fixed artifact evaluation"
~~~

Expected: no raw outputs/ file is committed.

### Task 2: Add selection contracts and the historical exposure registry

**Files:**
- Create: src/rsebench/selection/__init__.py
- Create: src/rsebench/selection/contracts.py
- Create: src/rsebench/selection/exposure.py
- Create: scripts/build_noise_screen_exposure.py
- Create: tests/selection/test_contracts.py
- Create: tests/selection/test_exposure.py
- Create: tests/validation/test_build_noise_screen_exposure.py

**Interfaces:**
- Consumes: StrictModel, TaskManifest, canonical_hash, and labeled manifest/result roots.
- Produces: ExposureRegistry, StableSplitCandidate, ConfirmationSplit, CandidateDecision, ScreeningGeneralizationDecision, ConfirmationSeal, SelectionReleaseManifest, selection_key(...), and build_exposure_registry(...).

- [ ] **Step 1: Write failing contract and precedence tests**

~~~python
def test_selection_key_is_role_sensitive() -> None:
    screen = selection_key(
        benchmark="officeqa_full",
        role="screening_test",
        candidate_index=2,
        stratum="hard|files=2-3",
        task_id="UID0042",
    )
    confirm = selection_key(
        benchmark="officeqa_full",
        role="confirmation_test",
        candidate_index=2,
        stratum="hard|files=2-3",
        task_id="UID0042",
    )
    assert len(screen) == 64
    assert screen != confirm


def test_score_observed_dominates_manifest_only(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    result = tmp_path / "result.json"
    manifest.write_text(json.dumps({"benchmark": "webshop", "train": [{"task_id": "goal_1"}]}))
    result.write_text(json.dumps({"benchmark": "webshop", "per_task_scores": {"goal_1": 1.0}}))
    registry = build_exposure_registry([
        ExposureSource(label="manifest", root=manifest, level=ExposureLevel.manifest_only),
        ExposureSource(label="result", root=result, level=ExposureLevel.score_observed),
    ])
    assert registry.records[0].level == ExposureLevel.score_observed
    assert registry.records[0].sources == ["manifest", "result"]
~~~

Also add a test that overlapping candidate roles raise ValueError containing disjoint and a test that serialized records never contain the source root's absolute path.

- [ ] **Step 2: Verify tests fail before implementation**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_contracts.py \
  tests/selection/test_exposure.py \
  tests/validation/test_build_noise_screen_exposure.py -q
~~~

Expected: collection fails because rsebench.selection does not exist.

- [ ] **Step 3: Implement strict immutable contracts**

Use these public shapes:

~~~python
class ExposureLevel(str, Enum):
    manifest_only = "manifest_only"
    executed = "executed"
    score_observed = "score_observed"

    @property
    def rank(self) -> int:
        return {
            ExposureLevel.manifest_only: 0,
            ExposureLevel.executed: 1,
            ExposureLevel.score_observed: 2,
        }[self]


class ExposureSource(StrictModel):
    label: str
    root: Path
    level: ExposureLevel
    experiment_id: str | None = None


class ExposureRecord(StrictModel):
    benchmark: str
    task_id: str
    source_partition: str | None = None
    level: ExposureLevel
    roles: list[str]
    sources: list[str]
    first_experiment_id: str | None = None
    last_experiment_id: str | None = None


class ExposureRegistry(StrictModel):
    schema_version: str = "rsebench.exposure-registry.v1"
    records: list[ExposureRecord]
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class StableSplitCandidate(StrictModel):
    schema_version: str = "rsebench.stable-split-candidate.v1"
    benchmark: str
    domain: str
    candidate_index: int = Field(ge=1, le=3)
    train: list[TaskManifest]
    validation: list[TaskManifest]
    qualification_test: list[TaskManifest]
    screening_test: list[TaskManifest]
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfirmationSplit(StrictModel):
    schema_version: str = "rsebench.confirmation-split.v1"
    benchmark: str
    domain: str
    train: list[TaskManifest]
    validation: list[TaskManifest]
    confirmation_test: list[TaskManifest]
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateSeedEvidence(StrictModel):
    method_seed: int
    accepted_update_count: int = Field(ge=0)
    artifact_changed: bool
    mean_delta_vs_seed: float
    execution_complete: bool
    replay_count: int = Field(ge=3)


class ScreeningSeedEvidence(StrictModel):
    method_seed: int
    mean_delta_vs_seed: float
    execution_complete: bool
    replay_count: int = Field(ge=3)


class ScreeningGeneralizationDecision(StrictModel):
    status: Literal["clean_generalization_ready", "clean_generalization_failed"]
    nondegrading_seed_count: int = Field(ge=0, le=3)
    mean_clean_gain: float
    execution_coverage: float = Field(ge=0.0, le=1.0)
    failure_reasons: list[str]


class CandidateDecision(StrictModel):
    schema_version: str = "rsebench.candidate-decision.v1"
    candidate_index: int = Field(ge=1, le=3)
    passed: bool
    accepted_seed_count: int = Field(ge=0, le=3)
    nondegrading_seed_count: int = Field(ge=0, le=3)
    mean_clean_gain: float
    execution_coverage: float = Field(ge=0.0, le=1.0)
    noise_applicability: float = Field(ge=0.0, le=1.0)
    next_action: Literal[
        "freeze_candidate",
        "run_candidate_2",
        "run_candidate_3",
        "extend_replay_to_5",
        "clean_blocked_after_three_candidates",
    ]
    failure_reasons: list[str]


SelectionAction = Literal[
    "replay_candidate_1",
    "rerun_candidate_1",
    "run_candidate_2",
    "run_candidate_3",
    "extend_replay_to_5",
    "freeze_candidate",
    "clean_blocked_after_three_candidates",
    "clean_blocked_skilllearn_families",
]


class DomainSelectionStatus(StrictModel):
    benchmark: str
    selected_candidate_index: int | None = Field(default=None, ge=1, le=3)
    next_action: SelectionAction
    reasons: list[str] = Field(default_factory=list)


class SelectionStatus(StrictModel):
    schema_version: str = "rsebench.selection-status.v1"
    domains: dict[str, DomainSelectionStatus]


class ConfirmationSeal(StrictModel):
    schema_version: str = "rsebench.confirmation-seal.v1"
    created_before_screening: bool
    split_hashes: dict[str, str]
    task_ids: dict[str, list[str]]
    exposure_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResourceReference(StrictModel):
    uri: str
    kind: Literal["git", "rsebench-data", "rsebench-methods", "external-image"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    materialization: str


class ResourceLock(StrictModel):
    schema_version: str = "rsebench.resource-lock.v1"
    resources: list[ResourceReference]


class SelectionReleaseManifest(StrictModel):
    schema_version: str = "rsebench.selection-release.v1"
    selection_version: Literal["noise-screen-v1"]
    selected_candidate_indices: dict[str, int]
    screening_split_hashes: dict[str, str]
    confirmation_split_hashes: dict[str, str]
    exposure_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_fingerprints: dict[str, str]
    domain_statuses: dict[str, Literal["clean_generalization_ready"]]


def selection_key(
    *, benchmark: str, role: str, candidate_index: int,
    stratum: str, task_id: str,
) -> str:
    return canonical_hash([
        "noise-screen-v1", benchmark, role,
        candidate_index, stratum, task_id,
    ])
~~~

Validators enforce unique IDs, disjoint roles, matching benchmark/domain, exact hash syntax, and fixed candidate bounds.

- [ ] **Step 4: Implement explicit exposure scanners**

~~~python
def build_exposure_registry(
    sources: Sequence[ExposureSource],
) -> ExposureRegistry:
    """Scan only declared ID-bearing fields and merge by level precedence."""


def merge_record(
    current: ExposureRecord | None,
    *,
    benchmark: str,
    task_id: str,
    role: str,
    source: ExposureSource,
) -> ExposureRecord:
    level = source.level
    if current is not None and current.level.rank > level.rank:
        level = current.level
    return ExposureRecord(
        benchmark=benchmark,
        task_id=task_id,
        level=level,
        roles=sorted(set((current.roles if current else []) + [role])),
        sources=sorted(set((current.sources if current else []) + [source.label])),
    )
~~~

Recognize task IDs only from declared split arrays, per_task_scores, task timing rows, goal_idx fields, and SkillLearn instance records. Do not recursively treat arbitrary strings as IDs. Compute registry_hash over sorted records before inserting the hash.

- [ ] **Step 5: Run tests and commit**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_contracts.py \
  tests/selection/test_exposure.py \
  tests/validation/test_build_noise_screen_exposure.py -q
ruff check src/rsebench/selection \
  scripts/build_noise_screen_exposure.py \
  tests/selection \
  tests/validation/test_build_noise_screen_exposure.py
git add src/rsebench/selection \
  scripts/build_noise_screen_exposure.py \
  tests/selection/test_contracts.py \
  tests/selection/test_exposure.py \
  tests/validation/test_build_noise_screen_exposure.py
git commit -m "feat: audit benchmark sample exposure"
~~~

Expected: all tests pass and the registry contains labels, never machine paths.

### Task 3: Generate deterministic candidate and confirmation manifests

**Files:**
- Create: src/rsebench/selection/splits.py
- Create: scripts/build_noise_screen_candidates.py
- Create: tests/selection/test_splits.py
- Create: tests/validation/test_build_noise_screen_candidates.py
- Modify: src/rsebench/core1/dataset.py
- Modify: tests/core1/test_dataset.py

**Interfaces:**
- Consumes: source splits, benchmark materializations, ExposureRegistry, and current clean-v2 manifests.
- Produces: build_selection_candidates(...) -> SelectionCandidateBundle and portable candidate/confirmation JSON.

SelectionCandidateBundle has this exact public contract:

~~~python
class SelectionCandidateBundle(StrictModel):
    schema_version: str = "rsebench.selection-candidate-bundle.v1"
    benchmark: str
    candidates: list[StableSplitCandidate]
    confirmation: ConfirmationSplit
    confirmation_seal: ConfirmationSeal

    @property
    def screening_all_ids(self) -> list[str]:
        return list(dict.fromkeys(
            task.task_id
            for candidate in self.candidates
            for task in (
                candidate.train
                + candidate.validation
                + candidate.qualification_test
                + candidate.screening_test
            )
        ))

    @property
    def confirmation_all_ids(self) -> list[str]:
        row = self.confirmation
        return list(dict.fromkeys(
            task.task_id
            for task in (
                row.train
                + row.validation
                + row.confirmation_test
            )
        ))

    @property
    def screening_test_ids(self) -> list[str]:
        return [task.task_id for task in self.candidates[0].screening_test]
~~~

- [ ] **Step 1: Write failing determinism, isolation, and count tests**

~~~python
def task_ids(tasks: Sequence[TaskManifest]) -> list[str]:
    return [task.task_id for task in tasks]


def test_candidate_two_changes_train_only(candidate_bundle) -> None:
    first, second = candidate_bundle.candidates[:2]
    assert task_ids(first.validation) == task_ids(second.validation)
    assert task_ids(first.qualification_test) == task_ids(second.qualification_test)
    assert task_ids(first.screening_test) == task_ids(second.screening_test)
    assert task_ids(first.train) != task_ids(second.train)


def test_confirmation_is_reserved_before_candidates(candidate_bundle) -> None:
    assert not set(candidate_bundle.screening_all_ids) & set(
        candidate_bundle.confirmation_all_ids
    )


def test_new_test_excludes_observed_tasks(candidate_bundle, exposure_registry) -> None:
    observed = {
        row.task_id for row in exposure_registry.records
        if row.level == ExposureLevel.score_observed
    }
    assert not set(candidate_bundle.screening_test_ids) & observed


def test_confirmation_excludes_historically_executed_tasks(
    candidate_bundle, exposure_registry
) -> None:
    executed = {
        row.task_id for row in exposure_registry.records
        if row.level.rank >= ExposureLevel.executed.rank
    }
    assert not set(candidate_bundle.confirmation_all_ids) & executed
~~~

Assert counts are Spreadsheet 20/10/30 + confirmation 20/10/30, OfficeQA 12/12/20 + 12/12/20, and WebShop 5/5/20 + 5/5/20. Assert the four fixed screening and four fixed confirmation SkillLearn family names.

Also add provider-free structural tests for the gates available before clean traces exist: Spreadsheet has 7/7/6 train batches and at least four operation categories; OfficeQA has 4/4/4 batches, excludes UID0240, and preserves difficulty/file-count/question-axis coverage; WebShop has unique normalized queries, reachable target ASINs, and exactly 2/5 validation headroom from the recorded retrieval audit; SkillLearn uses instance 1–2 for train, instance 3 for validation, and every remaining instance for its fixed test. N1/N2 static applicability must be 100%; N3/N4 trace-dependent applicability remains pending rather than being guessed.

- [ ] **Step 2: Run tests and confirm failure**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_splits.py \
  tests/validation/test_build_noise_screen_candidates.py -q
~~~

Expected: import failure for rsebench.selection.splits.

- [ ] **Step 3: Implement shared round-robin strata selection**

~~~python
def select_by_strata(
    tasks: Sequence[TaskManifest],
    *,
    count: int,
    benchmark: str,
    role: str,
    candidate_index: int,
    stratum: Callable[[TaskManifest], str],
    excluded_ids: set[str],
) -> list[TaskManifest]:
    groups: dict[str, list[TaskManifest]] = defaultdict(list)
    for task in tasks:
        if task.task_id not in excluded_ids:
            groups[stratum(task)].append(task)
    for name, rows in groups.items():
        rows.sort(key=lambda task: (
            selection_key(
                benchmark=benchmark,
                role=role,
                candidate_index=candidate_index,
                stratum=name,
                task_id=task.task_id,
            ),
            task.task_id,
        ))
    return round_robin_exact(groups, count=count)


def round_robin_exact(
    groups: Mapping[str, Sequence[TaskManifest]], *, count: int
) -> list[TaskManifest]:
    queues = {name: deque(rows) for name, rows in sorted(groups.items())}
    selected: list[TaskManifest] = []
    while len(selected) < count:
        progressed = False
        for name in sorted(queues):
            if queues[name]:
                selected.append(queues[name].popleft())
                progressed = True
                if len(selected) == count:
                    return selected
        if not progressed:
            raise ValueError(f"insufficient eligible pool: requested {count}")
    return selected
~~~

round_robin_exact fails when the pool is insufficient. Reserve confirmation first, then screening test, then Candidate 2/3 train sets. Candidate 1 imports current clean-v2 train/validation and qualification test.

- [ ] **Step 4: Implement exact domain strata**

Spreadsheet categories are lookup_join, aggregation_formula, text_date_cleaning, layout_chart_pivot, and other via a versioned keyword map. OfficeQA combines officeqa_stratum with one question axis: period, unit, entity, aggregation, or other. WebShop uses option-count, constraint-count, and retrieval-rank bins. SkillLearn screening uses organize-messy-files, offer-letter-generator, schedule-planning, and dependency-vulnerability-check; confirmation uses court-form-filling, earthquake-plate-calculation, dbscan-parameter-tuning, and travel-planning.

- [ ] **Step 5: Materialize portable task records**

Extend the clean path mapper so qualification_test and screening_test use the same rsebench-data:// and rsebench-methods:// normalization as clean_test. Retain verifier identity, task source hash, artifact hash, and ordered task IDs.

Candidate audit JSON records each static gate as pass/fail/pending. The clean qualification aggregator later resolves every N3/N4 pending item from actual trajectories; a pending item can never count as 100% noise applicability.

- [ ] **Step 6: Run tests and commit**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_splits.py \
  tests/validation/test_build_noise_screen_candidates.py \
  tests/core1/test_dataset.py -q
ruff check src/rsebench/selection/splits.py \
  scripts/build_noise_screen_candidates.py \
  tests/selection/test_splits.py \
  tests/validation/test_build_noise_screen_candidates.py
git add src/rsebench/selection/splits.py \
  src/rsebench/core1/dataset.py \
  scripts/build_noise_screen_candidates.py \
  tests/selection/test_splits.py \
  tests/validation/test_build_noise_screen_candidates.py \
  tests/core1/test_dataset.py
git commit -m "feat: build deterministic noise screen candidates"
~~~

Expected: all counts, exposure filters, hashes, and isolation tests pass.

### Task 4: Extend the clean control plane for selection candidates

**Files:**
- Modify: src/rsebench/experiments/preflight.py
- Modify: scripts/run_clean_skillopt.py
- Modify: scripts/run_clean_skilladaptor.py
- Modify: scripts/run_clean_skilllearn.py
- Modify: scripts/run_clean_qualification_matrix.py
- Create: configs/experiments/noise-screen-v1-candidate2.yaml
- Create: configs/experiments/noise-screen-v1-candidate3.yaml
- Create: configs/experiments/noise-screen-v1-reuse-fallback.yaml
- Modify: tests/experiments/test_preflight.py
- Modify: tests/validation/test_run_clean_qualification_matrix.py
- Modify: tests/validation/test_run_clean_skillopt.py
- Modify: tests/validation/test_run_clean_skilladaptor.py
- Modify: tests/validation/test_run_clean_skilllearn.py

**Interfaces:**
- Consumes: candidate manifests with qualification_version=noise-screen-v1.
- Produces: preflighted, isolated, resumable clean units under outputs/runs/noise-screen-v1-qualification, filtered only by typed next actions in selection_status.json.

- [ ] **Step 1: Write failing version and routing tests**

~~~python
def test_preflight_accepts_matrix_declared_noise_screen_version(
    monkeypatch, tmp_path: Path
) -> None:
    root, matrix_path, fingerprint = _fixture_project(tmp_path)
    monkeypatch.setenv("FIXTURE_API_KEY", "declared")
    matrix_payload = yaml.safe_load(matrix_path.read_text())
    matrix_payload["qualification_version"] = "noise-screen-v1"
    matrix_path.write_text(yaml.safe_dump(matrix_payload, sort_keys=False))
    manifest_path = root / "benchmark/fixture.json"
    manifest_payload = json.loads(manifest_path.read_text())
    manifest_payload["metadata"]["qualification_version"] = "noise-screen-v1"
    manifest_path.write_text(json.dumps(manifest_payload))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "noise screen fixture")
    result = preflight_matrix(
        matrix_path,
        project_root=root,
        package_file=root / "src/rsebench/__init__.py",
        fingerprint_resolver=lambda baseline: fingerprint,
    )
    assert result.units[0].identity.inputs.stage == "clean"


def test_matrix_uses_declared_skilllearn_manifests() -> None:
    config = load_config(Path("configs/experiments/noise-screen-v1-candidate2.yaml"))
    units = expand_units(config)
    skilllearn = [row for row in units if row.benchmark == "skilllearnbench"]
    assert len(units) == 21
    assert len(skilllearn) == 12
    assert all(
        "noise_screen_v1/candidates/skilllearnbench" in " ".join(row.command)
        for row in skilllearn
    )


def test_status_filter_starts_only_requested_candidate_cells(tmp_path: Path) -> None:
    config = load_config(Path("configs/experiments/noise-screen-v1-candidate2.yaml"))
    status = tmp_path / "selection_status.json"
    status.write_text(json.dumps({
        "schema_version": "rsebench.selection-status.v1",
        "domains": {
            "spreadsheetbench_verified": {
                "benchmark": "spreadsheetbench_verified",
                "next_action": "freeze_candidate",
            },
            "officeqa_full": {
                "benchmark": "officeqa_full",
                "next_action": "run_candidate_2",
            },
            "webshop": {
                "benchmark": "webshop",
                "next_action": "freeze_candidate",
            },
            "skilllearnbench": {
                "benchmark": "skilllearnbench",
                "next_action": "freeze_candidate",
            },
        }
    }))
    selected = select_units_from_status(
        expand_units(config),
        status_path=status,
        required_action="run_candidate_2",
        matrix_candidate_index=2,
    )
    assert {row.benchmark for row in selected} == {"officeqa_full"}
    assert len(selected) == 3
~~~

- [ ] **Step 2: Run tests and observe hard-coded v2/v1 failures**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/experiments/test_preflight.py \
  tests/validation/test_run_clean_qualification_matrix.py -q
~~~

Expected: new tests fail because preflight and launchers reject noise-screen-v1 or use a hard-coded SkillLearn root.

- [ ] **Step 3: Generalize version equality without accepting arbitrary versions**

~~~python
SUPPORTED_QUALIFICATION_VERSIONS = frozenset({
    "clean-qualification-v1",
    "clean-qualification-v2",
    "noise-screen-v1",
})


# In the existing ExperimentMatrix class, widen only this field:
qualification_version: Literal[
    "clean-qualification-v1",
    "clean-qualification-v2",
    "noise-screen-v1",
]


def require_manifest_version(*, expected: str, actual: str, cell_key: str) -> None:
    if expected not in SUPPORTED_QUALIFICATION_VERSIONS:
        raise ValueError(f"unsupported matrix qualification version: {expected}")
    if actual != expected:
        raise ValueError(
            f"manifest qualification version differs: {cell_key}: "
            f"{actual} != {expected}"
        )
~~~

Launchers require runtime identity for provider-active noise-screen-v1 runs. Runtime, task counts, model identity, and baseline fingerprints remain strict.

- [ ] **Step 4: Make SkillLearn paths and sequential cell selection declarative**

Read skilllearn.manifests[family] from YAML. Candidate 2 contains Spreadsheet, OfficeQA, WebShop, and four SkillLearn cells, totaling 21 units. Candidate 3 contains the three pool-based benchmarks, totaling 9 units. Reuse fallback has OfficeQA and WebShop Candidate 1, totaling 6 units. SkillLearn has one preregistered four-family split because its fixed 2/1/remainder allocation exhausts each small family; it does not silently swap families after results.

Add candidate_index to each selection YAML and implement the filter with this boundary:

~~~python
def select_units_from_status(
    units: Sequence[MatrixUnit],
    *,
    status_path: Path,
    required_action: SelectionAction,
    matrix_candidate_index: int,
) -> list[MatrixUnit]:
    status = SelectionStatus.model_validate_json(status_path.read_text())
    expected_suffix = f"candidate_{matrix_candidate_index}"
    if required_action.startswith(("run_candidate_", "rerun_candidate_")):
        if not required_action.endswith(expected_suffix):
            raise ValueError("selection action differs from matrix candidate index")
    requested = {
        benchmark
        for benchmark, row in status.domains.items()
        if row.next_action == required_action
    }
    unknown = requested - {unit.benchmark for unit in units}
    if unknown:
        raise ValueError(f"selection status contains unknown matrix domains: {unknown}")
    selected = [unit for unit in units if unit.benchmark in requested]
    if not selected:
        raise ValueError(f"no units request action {required_action}")
    return selected
~~~

Expose CLI options `--selection-status` plus `--required-action`. When present, the runner schedules only the filtered units. Scheduler resume continues to prevent duplicate completed units.

- [ ] **Step 5: Run control-plane tests and commit**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/experiments/test_preflight.py \
  tests/validation/test_run_clean_qualification_matrix.py \
  tests/validation/test_run_clean_skillopt.py \
  tests/validation/test_run_clean_skilladaptor.py \
  tests/validation/test_run_clean_skilllearn.py -q
ruff check src/rsebench/experiments/preflight.py \
  scripts/run_clean_skillopt.py \
  scripts/run_clean_skilladaptor.py \
  scripts/run_clean_skilllearn.py \
  scripts/run_clean_qualification_matrix.py
git add src/rsebench/experiments/preflight.py \
  scripts/run_clean_skillopt.py \
  scripts/run_clean_skilladaptor.py \
  scripts/run_clean_skilllearn.py \
  scripts/run_clean_qualification_matrix.py \
  configs/experiments/noise-screen-v1-candidate2.yaml \
  configs/experiments/noise-screen-v1-candidate3.yaml \
  configs/experiments/noise-screen-v1-reuse-fallback.yaml \
  tests/experiments/test_preflight.py \
  tests/validation/test_run_clean_qualification_matrix.py \
  tests/validation/test_run_clean_skillopt.py \
  tests/validation/test_run_clean_skilladaptor.py \
  tests/validation/test_run_clean_skilllearn.py
git commit -m "feat: run stable split clean qualification"
~~~

Expected: targeted tests pass, dry Candidate-2 expansion reports 21 units, and the status-filter test selects exactly the requested three OfficeQA seeds.

### Task 5: Add cross-baseline replay and candidate decisions

**Files:**
- Create: src/rsebench/selection/qualification.py
- Create: scripts/replay_fixed_skilladaptor_artifacts.py
- Create: scripts/replay_fixed_skilllearn_artifacts.py
- Create: scripts/run_noise_screen_replays.py
- Create: scripts/aggregate_noise_screen_selection.py
- Create: tests/selection/test_qualification.py
- Create: tests/validation/test_replay_fixed_skilladaptor_artifacts.py
- Create: tests/validation/test_replay_fixed_skilllearn_artifacts.py
- Create: tests/validation/test_aggregate_noise_screen_selection.py

**Interfaces:**
- Consumes: result identities, accepted updates, artifact hashes, execution/applicability audits, and RepeatedArtifactReplayResult.
- Produces: decide_candidate(...) -> CandidateDecision and selection_status.json.

- [ ] **Step 1: Write failing fixed-denominator tests**

~~~python
def seed_evidence(
    method_seed: int,
    *,
    accepted: int,
    changed: bool,
    mean_delta: float,
) -> CandidateSeedEvidence:
    return CandidateSeedEvidence(
        method_seed=method_seed,
        accepted_update_count=accepted,
        artifact_changed=changed,
        mean_delta_vs_seed=mean_delta,
        execution_complete=True,
        replay_count=3,
    )


def test_two_updates_two_nondegrading_and_positive_mean_pass() -> None:
    decision = decide_candidate(
        candidate_index=2,
        seeds=[
            seed_evidence(20260813, accepted=1, changed=True, mean_delta=0.08),
            seed_evidence(20260814, accepted=1, changed=True, mean_delta=0.03),
            seed_evidence(20260815, accepted=0, changed=False, mean_delta=0.00),
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is True
    assert decision.next_action == "freeze_candidate"


def test_failed_candidate_two_requests_candidate_three() -> None:
    decision = decide_candidate(
        candidate_index=2,
        seeds=[
            seed_evidence(20260813, accepted=0, changed=False, mean_delta=0.0),
            seed_evidence(20260814, accepted=1, changed=True, mean_delta=0.1),
            seed_evidence(20260815, accepted=0, changed=False, mean_delta=0.0),
        ],
        execution_coverage=1.0,
        noise_applicability=1.0,
    )
    assert decision.passed is False
    assert decision.next_action == "run_candidate_3"
~~~

Add tests that Candidate 3 fails closed, mixed fingerprints reject reuse, SkillLearn needs three ready families and emits clean_blocked_skilllearn_families rather than requesting a replacement family, sign-inconsistent three-repeat replays request five repeats, and screening generalization requires 2/3 nondegrading seeds plus a strictly positive three-seed mean at 100% execution coverage. Add domain-audit tests for Spreadsheet validation headroom [0.2, 0.8] and mixed batch outcomes, OfficeQA parseable-answer rate >=0.9 plus validation headroom [0.25, 0.75] and mixed batch outcomes, WebShop target reachability/2-of-5 validation headroom/15-step budget, and SkillLearn container/verifier completion without hidden-test leakage.

Every replay result test must assert run-level wall time, stage-level timing, task-level timing rows, prompt/completion/total tokens, and token-observation coverage. Missing timing or less than 100% token coverage blocks aggregation instead of being omitted from the report.

- [ ] **Step 2: Run tests and verify missing implementations**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_qualification.py \
  tests/validation/test_replay_fixed_skilladaptor_artifacts.py \
  tests/validation/test_replay_fixed_skilllearn_artifacts.py \
  tests/validation/test_aggregate_noise_screen_selection.py -q
~~~

Expected: imports fail for new qualification/replay components.

- [ ] **Step 3: Implement WebShop and SkillLearn executor adapters**

WebShop loads a frozen SkillBank and executes the exact 15-step environment. SkillLearn loads a frozen Markdown skill, uses the prebuilt family image, and calls SkillLearnExecutor.evaluate_task. Both implement EvolutionExecutor.evaluate and delegate all rotation, resume, timing, task-hash, and token logic to evaluate_repeated_artifacts.

- [ ] **Step 4: Implement the candidate decision**

~~~python
def decision_failures(
    *,
    seeds: Sequence[CandidateSeedEvidence],
    execution_coverage: float,
    noise_applicability: float,
) -> list[str]:
    reasons: list[str] = []
    accepted = sum(
        row.accepted_update_count > 0 and row.artifact_changed for row in seeds
    )
    nondegrading = sum(row.mean_delta_vs_seed >= 0.0 for row in seeds)
    mean_gain = statistics.fmean(row.mean_delta_vs_seed for row in seeds)
    if accepted < 2:
        reasons.append("fewer_than_two_accepted_artifact_updates")
    if nondegrading < 2:
        reasons.append("fewer_than_two_nondegrading_seed_replays")
    if mean_gain <= 0.0:
        reasons.append("nonpositive_mean_clean_gain")
    if execution_coverage != 1.0:
        reasons.append("incomplete_execution_coverage")
    if noise_applicability != 1.0:
        reasons.append("incomplete_noise_applicability")
    if not all(row.execution_complete for row in seeds):
        reasons.append("incomplete_seed_execution")
    return reasons


def decide_candidate(
    *,
    candidate_index: int,
    seeds: Sequence[CandidateSeedEvidence],
    execution_coverage: float,
    noise_applicability: float,
) -> CandidateDecision:
    if len(seeds) != 3 or len({row.method_seed for row in seeds}) != 3:
        raise ValueError("candidate decision requires exactly three unique seeds")
    accepted = [
        row for row in seeds
        if row.accepted_update_count > 0 and row.artifact_changed
    ]
    nondegrading = [
        row for row in seeds if row.mean_delta_vs_seed >= 0.0
    ]
    mean_gain = statistics.fmean(row.mean_delta_vs_seed for row in seeds)
    passed = (
        len(seeds) == 3
        and len(accepted) >= 2
        and len(nondegrading) >= 2
        and mean_gain > 0.0
        and execution_coverage == 1.0
        and noise_applicability == 1.0
        and all(row.execution_complete for row in seeds)
    )
    if passed:
        next_action = "freeze_candidate"
    elif candidate_index < 3:
        next_action = f"run_candidate_{candidate_index + 1}"
    else:
        next_action = "clean_blocked_after_three_candidates"
    return CandidateDecision(
        candidate_index=candidate_index,
        passed=passed,
        accepted_seed_count=len(accepted),
        nondegrading_seed_count=len(nondegrading),
        mean_clean_gain=mean_gain,
        execution_coverage=execution_coverage,
        noise_applicability=noise_applicability,
        next_action=next_action,
        failure_reasons=decision_failures(
            seeds=seeds,
            execution_coverage=execution_coverage,
            noise_applicability=noise_applicability,
        ),
    )
~~~

Before decide_candidate, use this explicit replay branch; the aggregator must
not silently collapse it:

~~~python
def replay_action(
    deltas: Sequence[float], *, repeats: int
) -> Literal["extend_replay_to_5", "decide_candidate"]:
    if not deltas:
        raise ValueError("replay action requires paired deltas")
    if repeats == 3 and min(deltas) < 0.0 < max(deltas):
        return "extend_replay_to_5"
    return "decide_candidate"


def decide_screening_generalization(
    *, seeds: Sequence[ScreeningSeedEvidence], execution_coverage: float
) -> ScreeningGeneralizationDecision:
    if len(seeds) != 3 or len({row.method_seed for row in seeds}) != 3:
        raise ValueError("screening decision requires exactly three unique seeds")
    nondegrading = sum(row.mean_delta_vs_seed >= 0.0 for row in seeds)
    mean_gain = statistics.fmean(row.mean_delta_vs_seed for row in seeds)
    ready = (
        nondegrading >= 2
        and mean_gain > 0.0
        and execution_coverage == 1.0
        and all(row.execution_complete for row in seeds)
    )
    reasons: list[str] = []
    if nondegrading < 2:
        reasons.append("fewer_than_two_nondegrading_screening_replays")
    if mean_gain <= 0.0:
        reasons.append("nonpositive_screening_mean_clean_gain")
    if execution_coverage != 1.0 or not all(
        row.execution_complete for row in seeds
    ):
        reasons.append("incomplete_screening_execution_coverage")
    return ScreeningGeneralizationDecision(
        status=(
            "clean_generalization_ready"
            if ready
            else "clean_generalization_failed"
        ),
        nondegrading_seed_count=nondegrading,
        mean_clean_gain=mean_gain,
        execution_coverage=execution_coverage,
        failure_reasons=reasons,
    )
~~~

Reuse requires matching baseline fingerprint, evolution-input hash, provider/model config, method seed, and artifact hash. Any mismatch requests the fixed fallback matrix.

The domain aggregator uses decide_candidate for the three pool-based benchmarks. SkillLearn aggregates four fixed family decisions, freezes when at least three are ready, and otherwise emits clean_blocked_skilllearn_families; it must not call decide_candidate to create a nonexistent SkillLearn Candidate 3.

Before constructing either decision, the aggregator merges the provider-free candidate audit with actual clean traces. It requires every N1/N2 static target and every N3/N4 trace target to be applicable, verifies the domain-specific headroom/batch gates above, and computes execution_coverage from the fixed expected task denominator. Any unresolved pending gate produces a typed failure reason rather than a pass.

- [ ] **Step 5: Run tests and commit**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_qualification.py \
  tests/validation/test_replay_fixed_skilladaptor_artifacts.py \
  tests/validation/test_replay_fixed_skilllearn_artifacts.py \
  tests/validation/test_aggregate_noise_screen_selection.py -q
ruff check src/rsebench/selection/qualification.py \
  scripts/replay_fixed_skilladaptor_artifacts.py \
  scripts/replay_fixed_skilllearn_artifacts.py \
  scripts/run_noise_screen_replays.py \
  scripts/aggregate_noise_screen_selection.py
git add src/rsebench/selection/qualification.py \
  scripts/replay_fixed_skilladaptor_artifacts.py \
  scripts/replay_fixed_skilllearn_artifacts.py \
  scripts/run_noise_screen_replays.py \
  scripts/aggregate_noise_screen_selection.py \
  tests/selection/test_qualification.py \
  tests/validation/test_replay_fixed_skilladaptor_artifacts.py \
  tests/validation/test_replay_fixed_skilllearn_artifacts.py \
  tests/validation/test_aggregate_noise_screen_selection.py
git commit -m "feat: qualify stable clean artifacts across baselines"
~~~

Expected: all replay and decision tests pass.

### Task 6: Freeze a portable, secret-safe selection release

**Files:**
- Create: src/rsebench/selection/release.py
- Create: scripts/freeze_noise_screen_selection.py
- Create: tests/selection/test_release.py
- Create: tests/validation/test_freeze_noise_screen_selection.py
- Modify: src/rsebench/cli.py
- Modify: tests/experiments/test_cli.py
- Create: benchmark/schemas/stable-split-candidate.schema.json
- Create: benchmark/schemas/confirmation-split.schema.json
- Create: benchmark/schemas/selection-release-manifest.schema.json

**Interfaces:**
- Consumes: passing candidate/generalization decisions, confirmation seal, exposure registry, resource hashes, and baseline fingerprints.
- Produces: freeze_selection_release(...) -> FrozenSelectionRelease and benchmark/validation/noise_screen_v1/.

Release decisions use a discriminated union: the three pool benchmarks retain
their exact `CandidateDecision`, while SkillLearn uses an immutable
`SkillLearnQualificationDecision` over all four fixed family summaries. The
root-owned production command re-derives these decisions and baseline
fingerprints from clean/replay evidence and requires byte-equivalent,
hash-bound `release_qualification.json`; it never promotes a passing status
into decision evidence.

- [ ] **Step 1: Write failing barrier and portability tests**

~~~python
def test_release_rejects_nonready_domain(tmp_path: Path, release_inputs) -> None:
    release_inputs["domain_statuses"]["webshop"] = "clean_generalization_failed"
    with pytest.raises(ValueError, match="clean_generalization_ready"):
        freeze_selection_release(
            destination=tmp_path / "release",
            **release_inputs,
        )


def test_release_is_portable_and_content_addressed(
    tmp_path: Path, release_inputs
) -> None:
    frozen = freeze_selection_release(
        destination=tmp_path / "release",
        **release_inputs,
    )
    payload = (tmp_path / "release" / "manifest.json").read_text()
    assert str(tmp_path) not in payload
    assert ".worktrees" not in payload
    assert len(frozen.release_id) == 64
    assert frozen.file_hashes["manifest.json"]
~~~

- [ ] **Step 2: Run tests and verify module absence**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_release.py \
  tests/validation/test_freeze_noise_screen_selection.py -q
~~~

Expected: import failure for rsebench.selection.release.

- [ ] **Step 3: Implement the atomic release barrier**

~~~python
def freeze_selection_release(
    *,
    destination: Path,
    candidates: Mapping[str, StableSplitCandidate],
    confirmations: Mapping[str, ConfirmationSplit],
    decisions: Mapping[str, ReleaseDomainDecision],
    domain_statuses: Mapping[str, str],
    exposure_registry: ExposureRegistry,
    confirmation_seal: ConfirmationSeal,
    resource_lock: ResourceLock,
    baseline_fingerprints: Mapping[str, str],
    qualification_companion: QualificationReleaseCompanion | None = None,
) -> FrozenSelectionRelease:
    expected_domains = {
        "spreadsheetbench_verified",
        "officeqa_full",
        "webshop",
        "skilllearnbench",
    }
    if set(domain_statuses) != expected_domains:
        raise ValueError("release requires exactly the four registered domains")
    if any(
        value != "clean_generalization_ready"
        for value in domain_statuses.values()
    ):
        raise ValueError("all domains must be clean_generalization_ready")
    if not confirmation_seal.created_before_screening:
        raise ValueError("confirmation split was not sealed before screening")
    validate_cross_release_disjointness(candidates, confirmations)
    files = build_release_files(
        candidates=candidates,
        confirmations=confirmations,
        decisions=decisions,
        domain_statuses=domain_statuses,
        exposure_registry=exposure_registry,
        confirmation_seal=confirmation_seal,
        resource_lock=resource_lock,
        baseline_fingerprints=baseline_fingerprints,
    )
    reject_secrets_and_absolute_paths(files)
    return atomic_content_addressed_write(destination, files)
~~~

The release helpers have these exact boundaries:

~~~python
class FrozenSelectionRelease(StrictModel):
    path: Path
    release_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_hashes: dict[str, str]


def validate_cross_release_disjointness(
    candidates: Mapping[str, StableSplitCandidate],
    confirmations: Mapping[str, ConfirmationSplit],
) -> None:
    """Raise ValueError when any domain shares screening and confirmation IDs."""


def build_release_files(
    *,
    candidates: Mapping[str, StableSplitCandidate],
    confirmations: Mapping[str, ConfirmationSplit],
    decisions: Mapping[str, ReleaseDomainDecision],
    domain_statuses: Mapping[str, str],
    exposure_registry: ExposureRegistry,
    confirmation_seal: ConfirmationSeal,
    resource_lock: ResourceLock,
    baseline_fingerprints: Mapping[str, str],
) -> dict[str, bytes]:
    """Return canonical UTF-8 JSON bytes keyed by repository-relative path."""


def reject_secrets_and_absolute_paths(files: Mapping[str, bytes]) -> None:
    """Reject credentials, /home paths, worktree paths, and unresolved URIs."""


def atomic_content_addressed_write(
    destination: Path, files: Mapping[str, bytes]
) -> FrozenSelectionRelease:
    """Hash the ordered file map, then write via a sibling temporary directory."""
~~~

ResourceLock classifies references as git, rsebench-data, rsebench-methods, or external-image; it records SHA-256 and rejects unresolved resources. Copy no large source dataset.

release_id is canonical_hash of the sorted `(relative_path, sha256(file_bytes))` map; manifest.json deliberately does not embed release_id, avoiding a circular hash. Atomic replacement uses a sibling temporary directory and refuses an existing destination unless every byte and hash already match.

- [ ] **Step 4: Add schema export and CLI**

Add selection freeze to the Typer app and export the three selection schemas. The CLI performs no provider call and refuses overwrite when bytes differ.

- [ ] **Step 5: Test and commit**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection/test_release.py \
  tests/validation/test_freeze_noise_screen_selection.py \
  tests/experiments/test_cli.py -q
ruff check src/rsebench/selection/release.py \
  scripts/freeze_noise_screen_selection.py \
  src/rsebench/cli.py
git add src/rsebench/selection/release.py \
  scripts/freeze_noise_screen_selection.py \
  src/rsebench/cli.py \
  tests/selection/test_release.py \
  tests/validation/test_freeze_noise_screen_selection.py \
  tests/experiments/test_cli.py \
  benchmark/schemas/stable-split-candidate.schema.json \
  benchmark/schemas/confirmation-split.schema.json \
  benchmark/schemas/selection-release-manifest.schema.json
git commit -m "feat: freeze portable stable split releases"
~~~

Expected: release and CLI tests pass with no absolute paths.

### Task 7: Generate and commit provider-free candidate IDs

**Files:**
- Generate: benchmark/validation/noise_screen_v1/exposure_registry.json
- Generate: benchmark/validation/noise_screen_v1/candidates/
- Generate: benchmark/validation/noise_screen_v1/confirmation_seal.json
- Generate: outputs/preflight/noise-screen-v1/

**Interfaces:**
- Consumes: Tasks 1–6 and local benchmark/method roots.
- Produces: immutable candidate IDs and a zero-provider-call commit required before formal runs.

- [ ] **Step 1: Run complete provider-free verification**

~~~bash
PYTHONPATH=src python -m pytest -q
ruff check src scripts tests
git diff --check
~~~

Expected: all tests and lint pass.

- [ ] **Step 2: Build exposure and candidates**

~~~bash
PYTHONPATH=src python scripts/build_noise_screen_exposure.py \
  --source main-manifests=benchmark:manifest_only \
  --source main-results=outputs:score_observed \
  --source pilot-results=.worktrees/rsebench-pilot/outputs:score_observed \
  --output benchmark/validation/noise_screen_v1/exposure_registry.json

PYTHONPATH=src python scripts/build_noise_screen_candidates.py \
  --exposure benchmark/validation/noise_screen_v1/exposure_registry.json \
  --data-root data \
  --methods-root methods/external \
  --output benchmark/validation/noise_screen_v1
~~~

Expected: three candidates per non-SkillLearn benchmark, one aggregate
SkillLearn `StableSplitCandidate` covering the four screening families, one aggregate
SkillLearn `ConfirmationSplit` covering the four sealed confirmation families, one
confirmation seal, and zero provider calls.

- [ ] **Step 3: Run baseline and experiment preflight**

~~~bash
PYTHONPATH=src python -m rsebench.cli baselines verify
PYTHONPATH=src python -m rsebench.cli experiment preflight \
  --matrix configs/experiments/noise-screen-v1-candidate2.yaml
PYTHONPATH=src python scripts/run_clean_qualification_matrix.py \
  --config configs/experiments/noise-screen-v1-candidate2.yaml
~~~

Expected: baselines verify, preflight reports zero calls, and dry matrix expansion prints units=21 provider_calls=0.

- [ ] **Step 4: Validate portable output**

~~~bash
PYTHONPATH=src python -m pytest \
  tests/selection \
  tests/validation/test_build_noise_screen_exposure.py \
  tests/validation/test_build_noise_screen_candidates.py -q
if rg -n '/home/|\.worktrees|DEEPSEEK_API_KEY|OPENAI_API_KEY|sk-' \
  benchmark/validation/noise_screen_v1; then exit 1; fi
~~~

Expected: tests pass and forbidden scan produces no match.

- [ ] **Step 5: Commit preregistered candidates**

~~~bash
git add benchmark/validation/noise_screen_v1 \
  configs/experiments/noise-screen-v1-candidate2.yaml \
  configs/experiments/noise-screen-v1-candidate3.yaml \
  configs/experiments/noise-screen-v1-reuse-fallback.yaml
git commit -m "data: preregister stable split candidates"
~~~

Expected: formal model calls begin from a clean immutable commit.

### Task 8: Run clean qualification and freeze the selected sample release

**Files:**
- Generate: outputs/runs/noise-screen-v1-qualification/
- Generate: benchmark/validation/noise_screen_v1/candidate_audits/
- Generate: benchmark/validation/noise_screen_v1/selection_status.json
- Generate: benchmark/validation/noise_screen_v1/screening_generalization.json
- Generate: benchmark/validation/noise_screen_v1/manifest.json
- Generate: benchmark/validation/noise_screen_v1/base_splits/
- Generate: benchmark/validation/noise_screen_v1/resource_lock.json
- Generate: releases/validation/noise-screen-v1/
- Create: docs/reports/2026-08-15-stable-noise-validation-splits.md

**Interfaces:**
- Consumes: clean candidate commit, environment credentials, current baseline fingerprints, and prebuilt SkillLearn images.
- Produces: the exact locally committed sample release later pushed to GitHub and shared across experiment repositories.

During provider-active work, mutable selection_status.json stays under the ignored run root so every formal matrix launch still sees a clean Git worktree. The atomic freeze step validates and copies its normalized form into benchmark/validation/noise_screen_v1/ only after all provider-backed runs have ended.

- [ ] **Step 1: Prebuild all eight screening/confirmation SkillLearn families**

~~~bash
PYTHONPATH=src python scripts/prebuild_clean_skilllearn_images.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --output outputs/preflight/noise-screen-v1/skilllearn_image_manifest.json
~~~

Expected: all_ready=true, and the image manifest covers every task in the four
screening plus four sealed confirmation families. The later resource-lock command
rejects partial image coverage. No formal token events are produced.

- [ ] **Step 2: Audit OfficeQA/WebShop Candidate-1 reuse**

~~~bash
PYTHONPATH=src python scripts/aggregate_noise_screen_selection.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --clean-v2-root outputs/runs/clean-v2-20260814 \
  --skillopt-replay-root outputs/runs/skillopt-fixed-replay-20260815 \
  --output outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --mode reuse-audit
~~~

Expected: typed OfficeQA/WebShop reuse decisions. The initial status requests Candidate 2 for the preregistered Spreadsheet failure and the four-family SkillLearn qualification; it requests replay_candidate_1 or rerun_candidate_1 for OfficeQA/WebShop. For any rerun_candidate_1 cell, run only the fixed fallback units selected by that status:

~~~bash
PYTHONPATH=src python scripts/run_clean_qualification_matrix.py \
  --config configs/experiments/noise-screen-v1-reuse-fallback.yaml \
  --selection-status outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --required-action rerun_candidate_1 \
  --execute --max-parallel 2
~~~

- [ ] **Step 3: Run the initially requested Candidate-2 cells**

~~~bash
PYTHONPATH=src python scripts/run_clean_qualification_matrix.py \
  --config configs/experiments/noise-screen-v1-candidate2.yaml \
  --selection-status outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --required-action run_candidate_2 \
  --execute --max-parallel 5
~~~

Expected: 15/15 scheduler units reach a terminal state; provider/system failures remain typed and resumable.

- [ ] **Step 4: Replay all available Candidate-1/2 artifacts and decide**

~~~bash
PYTHONPATH=src python scripts/run_noise_screen_replays.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --evaluation-role qualification_test \
  --repeats 3 \
  --execute --confirm-provider-cost

PYTHONPATH=src python scripts/aggregate_noise_screen_selection.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --output outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --mode qualification
~~~

Expected: each domain emits freeze_candidate, run_candidate_2, run_candidate_3, extend_replay_to_5, or a typed blocked reason. SkillLearn emits freeze_candidate only when at least three families are clean-ready; otherwise it emits clean_blocked_skilllearn_families and never substitutes a family. For extend_replay_to_5, rerun the replay command with --repeats 5 --resume, then aggregate again.

- [ ] **Step 5: Follow any newly requested Candidate-2 branch**

Only when the updated selection_status.json requests run_candidate_2 (normally an OfficeQA/WebShop Candidate-1 failure):

~~~bash
PYTHONPATH=src python scripts/run_clean_qualification_matrix.py \
  --config configs/experiments/noise-screen-v1-candidate2.yaml \
  --selection-status outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --required-action run_candidate_2 \
  --execute --max-parallel 2
PYTHONPATH=src python scripts/run_noise_screen_replays.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --candidate-index 2 \
  --evaluation-role qualification_test \
  --repeats 3 \
  --execute --confirm-provider-cost
PYTHONPATH=src python scripts/aggregate_noise_screen_selection.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --output outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --mode qualification
~~~

Expected: the runner starts only newly requested, incomplete Candidate-2 units; already completed Spreadsheet/SkillLearn units remain untouched.

- [ ] **Step 6: Follow the only permitted Candidate-3 branch**

Only when selection_status.json requests run_candidate_3:

~~~bash
PYTHONPATH=src python scripts/run_clean_qualification_matrix.py \
  --config configs/experiments/noise-screen-v1-candidate3.yaml \
  --selection-status outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --required-action run_candidate_3 \
  --execute --max-parallel 2
PYTHONPATH=src python scripts/run_noise_screen_replays.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --candidate-index 3 \
  --evaluation-role qualification_test \
  --repeats 3 \
  --execute --confirm-provider-cost
PYTHONPATH=src python scripts/aggregate_noise_screen_selection.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --output outputs/runs/noise-screen-v1-qualification/selection_status.json \
  --mode qualification
~~~

Expected: Candidate 3 freezes or returns clean_blocked_after_three_candidates. Never generate Candidate 4.

- [ ] **Step 7: Evaluate selected clean artifacts on new screening tests**

~~~bash
PYTHONPATH=src python scripts/run_noise_screen_replays.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --evaluation-role screening_test \
  --repeats 3 \
  --execute --confirm-provider-cost
PYTHONPATH=src python scripts/aggregate_noise_screen_selection.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --run-root outputs/runs/noise-screen-v1-qualification \
  --output outputs/runs/noise-screen-v1-qualification/screening_generalization.json \
  --mode screening-generalization
~~~

Expected: all four domains become clean_generalization_ready. If any fails, stop and report the exact gate without changing IDs.

- [ ] **Step 8: Freeze atomically and write the Chinese report**

~~~bash
PYTHONPATH=src python scripts/build_noise_screen_resource_lock.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --data-root "${RSEBENCH_DATA_ROOT:-data}" \
  --methods-root "${RSEBENCH_METHODS_ROOT:-methods/external}" \
  --methods-registry benchmark/registry/methods.yaml \
  --image-manifest outputs/preflight/noise-screen-v1/skilllearn_image_manifest.json \
  --output benchmark/validation/noise_screen_v1/resource_lock.json

PYTHONPATH=src python scripts/freeze_noise_screen_selection.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --release-root releases/validation/noise-screen-v1 \
  --run-root outputs/runs/noise-screen-v1-qualification
~~~

Expected: resource generation reports `provider_calls=0` and verifies every data/
method hash, all three baseline revisions/materializations, and every SkillLearn OCI
digest. Freeze revalidates those locks and recomputes both qualification and
screening from owned evidence; it refuses unless all four domains are ready. Success
prints one 64-character release ID.

The report lists exact train/validation/test IDs, confirmation counts/hashes, failed candidates, clean replay summaries, SkillLearn exposure exception, resource bootstrap requirements, release ID, calls/tokens, and run/stage/task timing. It explicitly states that N1–N4 have not run.

- [ ] **Step 9: Run final verification**

~~~bash
PYTHONPATH=src python -m pytest -q
ruff check src scripts tests
git diff --check
if rg -n '/home/|\.worktrees|DEEPSEEK_API_KEY|OPENAI_API_KEY|sk-' \
  benchmark/validation/noise_screen_v1 \
  releases/validation/noise-screen-v1; then exit 1; fi
~~~

Expected: all tests and lint pass; no absolute path or credential marker is found.

- [ ] **Step 10: Commit the Git-ready release locally**

~~~bash
git add benchmark/validation/noise_screen_v1 \
  releases/validation/noise-screen-v1 \
  docs/reports/2026-08-15-stable-noise-validation-splits.md
git commit -m "data: freeze stable noise validation splits"
~~~

Expected: commit contains portable manifests, compact evidence, resource locks, and report; raw outputs remain ignored. Do not push.
