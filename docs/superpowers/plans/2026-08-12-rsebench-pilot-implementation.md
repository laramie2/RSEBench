# RSE-Bench Phase 0–2 Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download and pin the selected baselines and datasets, build the shared benchmark/noise contracts, and run small SpreadsheetBench, OfficeQA, DocVQA, and DAPO noise-validation pilots with `deepseek-v4-flash` without touching GPT-5.5.

**Architecture:** The repository owns only manifests, adapters, generated-noise metadata, validators, and experiment code. Large datasets and baseline checkouts live in gitignored directories and are reproducibly materialized from pinned registries. Every noise generator implements `select → construct → inject → validate → calibrate`; DeepSeek calls go through one OpenAI-compatible client whose model is locked to `deepseek-v4-flash` for the pilot profile.

**Tech Stack:** Python 3.11+, uv/venv, Pydantic 2, PyYAML, Hugging Face Hub/Datasets, pandas/pyarrow, openpyxl, Pillow, httpx/OpenAI SDK, pytest, Git/Git LFS, Docker where required by baselines.

## Global Constraints

- Pilot execution and model-based noise generation use exactly `deepseek-v4-flash`; GPT-5.5 must not appear in active pilot configuration.
- DeepSeek uses the official OpenAI-compatible base URL `https://api.deepseek.com` and `DEEPSEEK_API_KEY` from `.env`.
- No API key is committed or printed; `.env` is gitignored and contains empty values until the user fills it.
- Pilot data is nested inside the evolution split; final validation and test IDs are never used to select operators or severity.
- Formal datasets, generated artifacts, logs, caches, and baseline clones are gitignored; manifests, hashes, configs, and code are committed.
- C1–C3 noise must preserve the original gold answer and official verifier; C4 is isolated as feedback-noise ablation.
- Rule/model outputs are cached before experiments, and experiment runs never regenerate benchmark noise implicitly.
- Native baseline reproduction precedes unified-harness comparisons.
- All repository code is developed with pytest-first tests and small commits.

---

## File Map

```text
pyproject.toml                         Python dependencies and test configuration
.gitignore                             Ignore secrets, data, baselines, cache, outputs
.env.example                           Empty DeepSeek/Hugging Face/runtime variables
.env                                   Empty local variables, gitignored
README.md                              Setup and pilot entry points
benchmark/registry/*.yaml              Pinned source, method, split, and operator registry
benchmark/schemas/*.json               Published JSON schemas
configs/pilot/*.yaml                   DeepSeek and domain pilot profiles
scripts/download/*.sh                  Reproducible baseline/data downloads
src/rsebench/contracts.py              Pydantic task/noise/validation contracts
src/rsebench/registry.py               YAML registry loader and validation
src/rsebench/hashing.py                File/tree SHA-256 helpers
src/rsebench/providers/deepseek.py      Locked DeepSeek V4 Flash client
src/rsebench/noise/base.py              Noise operator protocol and common result types
src/rsebench/noise/instruction.py       Cross-domain C1 operators
src/rsebench/domains/spreadsheet.py     Spreadsheet materializer/operators/validator
src/rsebench/domains/officeqa.py        OfficeQA retrieval decoys and validator
src/rsebench/domains/docvqa.py          DocVQA prompt/image-safe pilot support
src/rsebench/domains/math.py            DAPO flawed-solution generator and validator
src/rsebench/pilot.py                   Pilot-A/B planning and immutable run manifests
src/rsebench/cli.py                     Download/materialize/generate/validate/pilot CLI
tests/...                               Unit, fixture, and smoke tests
```

---

### Task 1: Repository Foundation and Locked Pilot Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `.env`
- Create: `README.md`
- Create: `src/rsebench/__init__.py`
- Create: `configs/pilot/deepseek-v4-flash.yaml`
- Test: `tests/test_project_config.py`

**Interfaces:**
- Consumes: approved design specification.
- Produces: installable `rsebench` package and a config that exposes `provider`, `base_url`, `model`, `api_key_env`, `temperature`, `max_tokens`, and `thinking`.

- [ ] **Step 1: Write failing configuration tests**

```python
from pathlib import Path
import yaml


ROOT = Path(__file__).parents[1]


def test_pilot_model_is_locked_to_deepseek_v4_flash():
    cfg = yaml.safe_load((ROOT / "configs/pilot/deepseek-v4-flash.yaml").read_text())
    assert cfg["provider"] == "deepseek"
    assert cfg["model"] == "deepseek-v4-flash"
    assert cfg["base_url"] == "https://api.deepseek.com"
    assert cfg["api_key_env"] == "DEEPSEEK_API_KEY"
    assert "gpt-5.5" not in str(cfg).lower()


def test_env_is_ignored_and_example_has_no_secret():
    assert ".env" in (ROOT / ".gitignore").read_text().splitlines()
    text = (ROOT / ".env.example").read_text()
    assert "DEEPSEEK_API_KEY=" in text
    assert not any(line.split("=", 1)[-1].strip() for line in text.splitlines() if "API_KEY=" in line)
```

- [ ] **Step 2: Run the tests and confirm they fail because files do not exist**

Run: `pytest tests/test_project_config.py -q`

Expected: failures naming missing `.gitignore`, `.env.example`, or pilot YAML.

- [ ] **Step 3: Add the minimal package and configuration**

`configs/pilot/deepseek-v4-flash.yaml`:

```yaml
provider: deepseek
base_url: https://api.deepseek.com
model: deepseek-v4-flash
api_key_env: DEEPSEEK_API_KEY
temperature: 0.0
max_tokens: 8192
thinking: enabled
timeout_seconds: 300
max_retries: 4
```

`.env.example` and local `.env`:

```dotenv
DEEPSEEK_API_KEY=
HF_TOKEN=
RSEBENCH_DATA_ROOT=/home/nvidia/yutao/lzt/self-evolution-robustness/data
RSEBENCH_OUTPUT_ROOT=/home/nvidia/yutao/lzt/self-evolution-robustness/outputs
```

`pyproject.toml` must define Python `>=3.11`, package source under `src`, dependencies `pydantic>=2.9`, `PyYAML>=6.0`, `httpx>=0.27`, `openai>=1.50`, `huggingface-hub>=0.27`, `datasets>=3.0`, `pandas>=2.2`, `pyarrow>=17`, `openpyxl>=3.1`, `Pillow>=10.4`, `python-dotenv>=1.0`, `typer>=0.12`, and test dependencies `pytest>=8.3`, `pytest-cov>=5.0`.

- [ ] **Step 4: Install and verify**

Run: `python -m pip install -e '.[test]' && pytest tests/test_project_config.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore .env.example README.md pyproject.toml configs src tests
git commit -m "chore: initialize rsebench pilot project"
```

---

### Task 2: Pinned Baseline and Dataset Registries

**Files:**
- Create: `benchmark/registry/methods.yaml`
- Create: `benchmark/registry/benchmarks.yaml`
- Create: `benchmark/registry/splits.yaml`
- Create: `benchmark/registry/noise_operators.yaml`
- Create: `src/rsebench/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: YAML registry path.
- Produces: `load_registry(path: Path) -> dict` and `validate_registries(root: Path) -> None`.

- [ ] **Step 1: Write failing registry tests**

```python
from pathlib import Path
from rsebench.registry import load_registry, validate_registries


ROOT = Path(__file__).parents[1]


def test_every_method_has_full_commit_and_repository():
    methods = load_registry(ROOT / "benchmark/registry/methods.yaml")["methods"]
    assert {"trace2skill", "skillopt", "skillgrad", "evoskill"} <= set(methods)
    assert all(len(row["commit"]) == 40 for row in methods.values())
    assert all(row["repository"].startswith("https://github.com/") for row in methods.values())


def test_registries_are_cross_reference_valid():
    validate_registries(ROOT / "benchmark/registry")
```

- [ ] **Step 2: Run tests and confirm missing-module/file failure**

Run: `pytest tests/test_registry.py -q`

Expected: import or file-not-found failure.

- [ ] **Step 3: Implement pinned registries and validation**

`methods.yaml` pins the audited commits from the design document. `benchmarks.yaml` contains source kind (`github`, `huggingface`), repository ID, revision when available, expected gated status, local relative path, and license-review flag. `splits.yaml` encodes the target counts and group key:

```yaml
splits:
  spreadsheetbench_verified:
    total: 400
    group_key: id
    evolution: 200
    pilot_evolve: 30
    pilot_eval: 10
    validation: 20
    test: 180
  officeqa_full:
    total: 246
    group_key: source_files
    evolution: 50
    pilot_evolve: 12
    pilot_eval: 8
    validation: 24
    test: 172
  docvqa_10pct:
    total: 534
    group_key: docId
    evolution: 107
    pilot_evolve: 20
    pilot_eval: 10
    validation: 53
    test: 374
  dapo_fixed_1000:
    total: 1000
    group_key: normalized_problem_hash
    evolution: 400
    pilot_evolve: 30
    pilot_eval: 20
    validation: 100
    test: 500
```

Validation rejects unknown benchmark references, malformed commits, pilot counts exceeding evolution counts, and split totals that do not match `total`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_registry.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add benchmark/registry src/rsebench/registry.py tests/test_registry.py
git commit -m "feat: add pinned method and benchmark registries"
```

---

### Task 3: Reproducible Baseline Download and Audit

**Files:**
- Create: `scripts/download/baselines.sh`
- Create: `scripts/audit_baselines.py`
- Create: `tests/test_download_scripts.py`

**Interfaces:**
- Consumes: `benchmark/registry/methods.yaml`, optional `RSEBENCH_METHODS_ROOT`.
- Produces: pinned clones under `methods/external/<name>` and `outputs/audits/baselines.json`.

- [ ] **Step 1: Write shell/static tests**

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_baseline_downloader_is_non_destructive_and_registry_driven():
    text = (ROOT / "scripts/download/baselines.sh").read_text()
    assert "methods.yaml" in text
    assert "git clone" in text
    assert "git checkout --detach" in text
    assert "rm -rf" not in text
```

- [ ] **Step 2: Run test and confirm missing-file failure**

Run: `pytest tests/test_download_scripts.py -q`

- [ ] **Step 3: Implement idempotent downloader**

The downloader must:

1. parse YAML with a short Python expression rather than duplicate URLs;
2. clone only when the target does not exist;
3. verify an existing target's origin before fetching;
4. fetch the pinned commit and checkout detached;
5. run `git lfs pull` only for methods whose registry sets `git_lfs: true`;
6. fail if the resulting `HEAD` differs from the registry commit;
7. never delete or reset an existing checkout.

- [ ] **Step 4: Run script and audit**

Run: `bash scripts/download/baselines.sh && python scripts/audit_baselines.py`

Expected: Trace2Skill, SkillOpt, SkillGrad, EvoSkill, Skills-Coach, CoEvoSkills, FederatedSkill, SkillsBench, and SkillFlow exist at pinned commits; the audit records size, HEAD, origin, dirty state, and code-availability notes.

- [ ] **Step 5: Re-run to prove idempotence**

Run: `bash scripts/download/baselines.sh`

Expected: all entries report already present and verified; no checkout is replaced.

- [ ] **Step 6: Commit scripts and audit manifest, not clones**

```bash
git add scripts/download scripts/audit_baselines.py tests/test_download_scripts.py benchmark/registry
git commit -m "feat: add reproducible baseline downloader"
```

---

### Task 4: Dataset Download, Materialization, and Inventory

**Files:**
- Create: `scripts/download/datasets.py`
- Create: `scripts/audit_datasets.py`
- Create: `benchmark/registry/data_inventory.yaml`
- Test: `tests/test_dataset_download.py`

**Interfaces:**
- Consumes: benchmark registry and `RSEBENCH_DATA_ROOT`.
- Produces: immutable source snapshots under `data/raw`, materialized subsets under `data/materialized`, and `outputs/audits/datasets.json`.

- [ ] **Step 1: Write failing dry-run test**

```python
from pathlib import Path
from scripts.download.datasets import build_download_plan


def test_core_download_plan_contains_required_sources(tmp_path: Path):
    plan = build_download_plan(tmp_path)
    ids = {item.source_id for item in plan}
    assert "KAKA22/SpreadsheetBench" in ids
    assert "databricks/officeqa" in ids
    assert "lmms-lab/DocVQA" in ids
    assert "BytedTsinghua-SIA/DAPO-Math-17k" in ids
    assert "LiveMathematicianBench/LiveMathematicianBench" in ids
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_dataset_download.py -q`

- [ ] **Step 3: Implement source-specific download strategies**

- SpreadsheetBench: Hugging Face snapshot plus the Trace2Skill released Verified-400 copy; compare task IDs and workbook hashes where equivalent.
- OfficeQA: authenticated Hugging Face snapshot of metadata plus parsed TXT corpus; defer PDF corpus unless a selected task requires it.
- DocVQA: download only files needed by SkillOpt's fixed 534-ID validation subset, not the entire 9.5 GB dataset when selective download is supported.
- DAPO: stream/select exactly 1,000 deterministic unique rows, then save local Parquet with source indices and hashes.
- WikiTableQuestions: official GitHub data snapshot.
- LiveMathematicianBench: official monthly JSON snapshot used by SkillOpt manifest.
- AIME 2026: MathArena official dataset/config snapshot.
- Skill-native assets: clone metadata now; defer SkillFlow 1.6 GB task payload until the main domain pilot is operational.

Downloads use `.partial` targets and atomic rename. Existing files are hash-checked and never silently overwritten.

- [ ] **Step 4: Execute core downloads**

Run: `python scripts/download/datasets.py --profile core --resume`

Expected: source snapshots complete or, for gated/unavailable files, an explicit actionable status in the audit rather than a partial success claim.

- [ ] **Step 5: Audit sizes, schemas, rows, and licenses**

Run: `python scripts/audit_datasets.py`

Expected: each dataset has source revision, local bytes, row/task count, fields, license, gated status, and checksum summary.

- [ ] **Step 6: Commit only code and inventory**

```bash
git add scripts/download/datasets.py scripts/audit_datasets.py benchmark/registry/data_inventory.yaml tests/test_dataset_download.py
git commit -m "feat: add benchmark dataset materialization"
```

---

### Task 5: Shared Task and Noise Contracts

**Files:**
- Create: `src/rsebench/contracts.py`
- Create: `src/rsebench/hashing.py`
- Create: `benchmark/schemas/task-manifest.schema.json`
- Create: `benchmark/schemas/noise-manifest.schema.json`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Produces: `TaskManifest`, `NoiseManifest`, `Severity`, `ValidationReport`, `sha256_file(path)`, and `sha256_tree(path)`.

- [ ] **Step 1: Write failing round-trip and invariant tests**

```python
import pytest
from rsebench.contracts import NoiseManifest, Severity, ValidationReport


def test_noise_manifest_round_trip():
    row = NoiseManifest(
        noise_id="dapo-C1-M2-flawed-solution-L2-s42",
        channel="C1",
        mechanism="M2",
        operator="flawed_partial_solution",
        domain="math",
        benchmark="dapo",
        severity=Severity(level="L2", budget=1, semantic_similarity=0.8),
        seed=42,
        clean_hash="a" * 64,
    )
    assert NoiseManifest.model_validate_json(row.model_dump_json()) == row


def test_validated_noise_requires_all_hard_gates():
    with pytest.raises(ValueError):
        ValidationReport(structural_valid=True, label_invariant=False, solvable=True, answer_leak_free=True, accepted=True)
```

- [ ] **Step 2: Run and confirm missing-model failure**

Run: `pytest tests/test_contracts.py -q`

- [ ] **Step 3: Implement strict Pydantic contracts**

Enums restrict channel to C1–C4, mechanism to M1–M6, severity to L0–L3, timing to evolution/test, and generator mode to rule/model/hybrid. `ValidationReport.accepted=True` is valid only when all hard gates are true.

- [ ] **Step 4: Export JSON schemas and run tests**

Run: `python -m rsebench.cli export-schemas && pytest tests/test_contracts.py -q`

Expected: tests pass and schemas parse as JSON.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/contracts.py src/rsebench/hashing.py benchmark/schemas tests/test_contracts.py
git commit -m "feat: define benchmark and noise contracts"
```

---

### Task 6: DeepSeek V4 Flash Provider with Offline Cache

**Files:**
- Create: `src/rsebench/providers/__init__.py`
- Create: `src/rsebench/providers/deepseek.py`
- Test: `tests/providers/test_deepseek.py`

**Interfaces:**
- Produces: `DeepSeekClient.from_yaml(path)`, `complete(messages, response_format=None, cache_key=None) -> ModelResponse`, and `has_credentials() -> bool`.

- [ ] **Step 1: Write failing mock-client tests**

```python
from pathlib import Path
from rsebench.providers.deepseek import DeepSeekClient


def test_client_rejects_non_flash_model(tmp_path: Path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("provider: deepseek\nbase_url: https://api.deepseek.com\nmodel: gpt-5.5\napi_key_env: DEEPSEEK_API_KEY\n")
    try:
        DeepSeekClient.from_yaml(cfg)
    except ValueError as exc:
        assert "deepseek-v4-flash" in str(exc)
    else:
        raise AssertionError("non-pilot model was accepted")


def test_cached_response_does_not_require_credentials(tmp_path: Path):
    client = DeepSeekClient.for_test(cache_dir=tmp_path)
    client.write_cache("fixture", {"content": "ok", "usage": {}})
    assert client.complete([{"role": "user", "content": "x"}], cache_key="fixture").content == "ok"
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/providers/test_deepseek.py -q`

- [ ] **Step 3: Implement provider**

The provider uses the OpenAI SDK with `base_url=https://api.deepseek.com`, refuses any model other than `deepseek-v4-flash`, loads the key only at call time, supports exponential retry for 429/5xx, writes atomic JSON cache files, records model/temperature/token usage, and redacts authorization headers and keys from errors.

- [ ] **Step 4: Run offline tests and optional connectivity check**

Run: `pytest tests/providers/test_deepseek.py -q`

If credentials exist, run: `python -m rsebench.cli provider-check --config configs/pilot/deepseek-v4-flash.yaml`

Expected without credentials: explicit `credentials_missing` status, no network call. Expected with credentials: model ID returned as `deepseek-v4-flash`.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/providers tests/providers configs/pilot
git commit -m "feat: add locked deepseek flash provider"
```

---

### Task 7: Cross-Domain C1 Instruction Noise

**Files:**
- Create: `src/rsebench/noise/__init__.py`
- Create: `src/rsebench/noise/base.py`
- Create: `src/rsebench/noise/instruction.py`
- Create: `configs/pilot/instruction-noise.yaml`
- Test: `tests/noise/test_instruction.py`

**Interfaces:**
- Produces: `NoiseOperator.generate(task, severity, seed) -> GeneratedNoise`; `RedundantContext`, `RelatedDistractor`, and `FailedAttempt`.

- [ ] **Step 1: Write deterministic and label-preserving tests**

```python
from rsebench.noise.instruction import FailedAttempt


def test_failed_attempt_is_deterministic_and_keeps_original_objective(task_fixture):
    op = FailedAttempt(model=None)
    a = op.generate(task_fixture, severity="L1", seed=7)
    b = op.generate(task_fixture, severity="L1", seed=7)
    assert a.payload == b.payload
    assert task_fixture.prompt in a.payload["prompt"]
    assert "失败" in a.payload["prompt"] or "尝试" in a.payload["prompt"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/noise/test_instruction.py -q`

- [ ] **Step 3: Implement rule and model-backed paths**

Rule mode builds controlled neutral wrappers. Model mode asks DeepSeek for JSON fields `background`, `failed_attempt`, `incorrect_hint`, and `why_non_binding`, then validates that the original prompt is included verbatim and the addition is explicitly non-authoritative. Cache keys include task hash, operator, severity, prompt-template version, and seed.

- [ ] **Step 4: Run tests**

Run: `pytest tests/noise/test_instruction.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/noise configs/pilot/instruction-noise.yaml tests/noise
git commit -m "feat: add cross-domain instruction noise"
```

---

### Task 8: Spreadsheet Noise and Official-Style Validation

**Files:**
- Create: `src/rsebench/domains/__init__.py`
- Create: `src/rsebench/domains/spreadsheet.py`
- Create: `configs/pilot/spreadsheet.yaml`
- Create: `tests/fixtures/spreadsheet/clean.xlsx`
- Create: `tests/fixtures/spreadsheet/answer.xlsx`
- Test: `tests/domains/test_spreadsheet.py`

**Interfaces:**
- Produces: `SpreadsheetTask`, `inject_backup_sheet`, `inject_semantic_decoy_sheet`, `compare_answer_range`, and `validate_spreadsheet_noise`.

- [ ] **Step 1: Write failing fixture tests**

```python
from openpyxl import load_workbook
from rsebench.domains.spreadsheet import inject_backup_sheet, validate_spreadsheet_noise


def test_backup_sheet_preserves_original_sheets_and_answer(tmp_path, spreadsheet_task):
    result = inject_backup_sheet(spreadsheet_task, tmp_path / "noisy.xlsx", severity="L2", seed=42)
    wb = load_workbook(result.output_path, data_only=False)
    assert "Backup_Archive" in wb.sheetnames
    assert set(spreadsheet_task.original_sheets) <= set(wb.sheetnames)
    report = validate_spreadsheet_noise(spreadsheet_task, result)
    assert report.structural_valid
    assert report.label_invariant
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/domains/test_spreadsheet.py -q`

- [ ] **Step 3: Implement protected-range and dependency-aware injection**

The selector records original sheets, named ranges, answer sheet/range, data range, formulas, and formula references. `inject_backup_sheet` adds a clearly stale copied sheet without altering originals. `inject_semantic_decoy_sheet` samples schema but changes only the copied values and labels the sheet Draft/Archive. Validation loads with openpyxl both `data_only=False/True`, compares original workbook sheets and formulas, and executes the ported SpreadsheetBench answer-range comparator.

- [ ] **Step 4: Run unit and 10-task materialization smoke tests**

Run: `pytest tests/domains/test_spreadsheet.py -q && python -m rsebench.cli generate-noise --profile configs/pilot/spreadsheet.yaml --limit 10 --offline`

Expected: all ten generated workbooks pass hard gates.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/domains/spreadsheet.py configs/pilot/spreadsheet.yaml tests/domains tests/fixtures/spreadsheet
git commit -m "feat: add spreadsheet artifact noise pilot"
```

---

### Task 9: OfficeQA Retrieval Noise

**Files:**
- Create: `src/rsebench/domains/officeqa.py`
- Create: `configs/pilot/officeqa.yaml`
- Test: `tests/domains/test_officeqa.py`

**Interfaces:**
- Produces: `build_corpus_index`, `select_decoy_documents`, `build_rank_fixture`, and `validate_officeqa_noise`.

- [ ] **Step 1: Write failing rank and gold-presence tests**

```python
from rsebench.domains.officeqa import build_rank_fixture


def test_rank_fixture_moves_but_never_removes_gold(officeqa_task):
    fixture = build_rank_fixture(officeqa_task, decoys=["decoy-a", "decoy-b"], gold_rank=3)
    assert fixture.results[2].document_id == officeqa_task.gold_document_id
    assert sum(r.document_id == officeqa_task.gold_document_id for r in fixture.results) == 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/domains/test_officeqa.py -q`

- [ ] **Step 3: Implement lexical/semantic decoy selection**

Start with deterministic BM25-like token overlap using the parsed corpus; optional embeddings are a later enhancement. Reject the gold document, exact duplicates, and candidates containing normalized ground truth. Record date/entity/unit differences where detectable. Build immutable per-task retrieval fixtures for gold ranks 3, 5, and 10.

- [ ] **Step 4: Run unit and 10-task offline smoke tests**

Run: `pytest tests/domains/test_officeqa.py -q && python -m rsebench.cli generate-noise --profile configs/pilot/officeqa.yaml --limit 10 --offline`

Expected: gold recall 100%, no candidate directly contains the normalized answer, all fixture hashes recorded.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/domains/officeqa.py configs/pilot/officeqa.yaml tests/domains/test_officeqa.py
git commit -m "feat: add officeqa retrieval noise pilot"
```

---

### Task 10: DocVQA Answer-Safe Pilot

**Files:**
- Create: `src/rsebench/domains/docvqa.py`
- Create: `configs/pilot/docvqa.yaml`
- Test: `tests/domains/test_docvqa.py`

**Interfaces:**
- Produces: `locate_answer_regions`, `inject_margin_clutter`, and `validate_docvqa_noise`.

- [ ] **Step 1: Write failing protection-mask test**

```python
from rsebench.domains.docvqa import inject_margin_clutter


def test_margin_clutter_never_intersects_answer_boxes(tmp_path, docvqa_task):
    result = inject_margin_clutter(docvqa_task, tmp_path / "noisy.png", severity="L1", seed=5)
    assert all(not added.intersects(answer) for added in result.added_boxes for answer in docvqa_task.answer_boxes)
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/domains/test_docvqa.py -q`

- [ ] **Step 3: Implement prompt-first and conservative image support**

The pilot first supports C1 prompt noise for all fixed IDs. Image noise is generated only when OCR or supplied annotations locate every accepted answer and a safe margin exists. Otherwise the sample is marked `not_applicable`, not failed or forced. Pillow draws deterministic stamps/page markers outside the protection mask; no image-wide degradation enters the first pilot.

- [ ] **Step 4: Run tests and applicability audit**

Run: `pytest tests/domains/test_docvqa.py -q && python -m rsebench.cli generate-noise --profile configs/pilot/docvqa.yaml --limit 10 --offline`

Expected: every generated image passes non-intersection; inapplicable cases are explicitly counted.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/domains/docvqa.py configs/pilot/docvqa.yaml tests/domains/test_docvqa.py
git commit -m "feat: add answer-safe docvqa pilot"
```

---

### Task 11: DAPO Math Noise with DeepSeek Critics

**Files:**
- Create: `src/rsebench/domains/math.py`
- Create: `configs/pilot/math.yaml`
- Create: `src/rsebench/prompts/math_noise.py`
- Test: `tests/domains/test_math.py`

**Interfaces:**
- Produces: `generate_flawed_solution`, `validate_flawed_solution`, `scan_answer_leak`, and `MathNoiseCandidate`.

- [ ] **Step 1: Write failing leakage and wrapper tests**

```python
from rsebench.domains.math import scan_answer_leak, wrap_failed_attempt


def test_answer_leak_detects_normalized_ground_truth():
    assert scan_answer_leak("The result is \\boxed{34}.", "34")


def test_wrapper_preserves_problem_and_marks_attempt_non_authoritative():
    prompt = wrap_failed_attempt("Find x.", "I divided by zero.")
    assert "Find x." in prompt
    assert "失败" in prompt or "可能有误" in prompt
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/domains/test_math.py -q`

- [ ] **Step 3: Implement cached generator/critic protocol**

DeepSeek generator returns strict JSON with `partial_solution`, `error_step`, `error_type`, and `incorrect_conclusion`. Critic A must locate the same error; Critic B must return `valid_proof=false`; leakage scan must find neither normalized answer nor boxed equivalent. Failed candidates retry at most twice and then record rejection.

- [ ] **Step 4: Run offline unit tests and credential-gated 5-task generation**

Run: `pytest tests/domains/test_math.py -q`

With credentials: `python -m rsebench.cli generate-noise --profile configs/pilot/math.yaml --limit 5`

Without credentials: expected explicit blocked status after all offline tests pass; no fallback model is allowed.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/domains/math.py src/rsebench/prompts configs/pilot/math.yaml tests/domains/test_math.py
git commit -m "feat: add deepseek math noise pilot"
```

---

### Task 12: Pilot Manifests, Calibration, and Baseline Mini-Evolution

**Files:**
- Create: `src/rsebench/pilot.py`
- Create: `src/rsebench/calibration.py`
- Create: `configs/pilot/pilot-a.yaml`
- Create: `configs/pilot/pilot-b.yaml`
- Create: `scripts/run/pilot_a.sh`
- Create: `scripts/run/pilot_b.sh`
- Test: `tests/test_pilot.py`

**Interfaces:**
- Produces: `build_pilot_manifest`, `evaluate_operator_gates`, `PilotDecision`, and immutable run directories containing config, inputs, outputs, costs, hashes, and status.

- [ ] **Step 1: Write failing split-isolation and gate tests**

```python
from rsebench.calibration import OperatorMetrics, evaluate_operator_gates


def test_pilot_ids_are_subset_of_evolution(split_manifest):
    assert set(split_manifest.pilot_evolve) <= set(split_manifest.evolution)
    assert set(split_manifest.pilot_eval) <= set(split_manifest.evolution)
    assert not set(split_manifest.pilot_eval) & set(split_manifest.test)


def test_operator_rejected_when_label_invariance_is_not_perfect():
    metrics = OperatorMetrics(structural_rate=1.0, label_invariance_rate=0.99, leakage_rate=0.0, clean_score=0.8, noisy_l2_score=0.68)
    assert not evaluate_operator_gates(metrics).accepted
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/test_pilot.py -q`

- [ ] **Step 3: Implement Pilot-A**

Pilot-A executes fixed initial skill on clean/L1/L2/L3 paired tasks. It computes structural validity, label invariance, applicability, leakage, clean/noisy score, severity monotonicity, floor ratio, token/call cost, and a decision with explicit failed gates.

- [ ] **Step 4: Implement Pilot-B adapters for representative baselines**

Add thin invocation wrappers, without changing baseline algorithms:

- Spreadsheet: SkillOpt and Trace2Skill;
- OfficeQA: SkillOpt and EvoSkill;
- DocVQA: SkillOpt and Trace2Skill;
- DAPO: Trace2Skill and SkillOpt's common adapter.

Each wrapper receives the same pilot manifest and DeepSeek provider config. Unsupported paths return `unsupported_with_reason`, never a fabricated score.

- [ ] **Step 5: Run offline Pilot-A smoke and model-backed pilot when credentials exist**

Run: `bash scripts/run/pilot_a.sh --offline --limit 5`

With credentials: `bash scripts/run/pilot_a.sh --model-config configs/pilot/deepseek-v4-flash.yaml`

Then: `bash scripts/run/pilot_b.sh --model-config configs/pilot/deepseek-v4-flash.yaml --methods skillopt,trace2skill`

Expected: immutable run directories and an operator decision report; no GPT-5.5 calls.

- [ ] **Step 6: Commit**

```bash
git add src/rsebench/pilot.py src/rsebench/calibration.py configs/pilot scripts/run tests/test_pilot.py
git commit -m "feat: add rsebench pilot calibration workflow"
```

---

### Task 13: End-to-End Verification and Research Handoff

**Files:**
- Create: `docs/reports/phase0-download-audit.md`
- Create: `docs/reports/pilot-readiness.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all earlier outputs.
- Produces: evidence-backed readiness report and exact next commands.

- [ ] **Step 1: Run the full offline test suite**

Run: `pytest --cov=src/rsebench --cov-report=term-missing -q`

Expected: zero failures and at least 80% line coverage for implemented pilot code.

- [ ] **Step 2: Verify registries, source hashes, and no secrets**

Run:

```bash
python -m rsebench.cli registry-check
python scripts/audit_baselines.py
python scripts/audit_datasets.py
git grep -nE 'sk-[A-Za-z0-9_-]{16,}|DEEPSEEK_API_KEY=.+' -- ':!docs/superpowers/plans/*'
```

Expected: registry check passes; audits report exact statuses; secret grep returns no matches.

- [ ] **Step 3: Run formal 10-task offline generation smoke per domain**

Run:

```bash
python -m rsebench.cli generate-noise --profile configs/pilot/spreadsheet.yaml --limit 10 --offline
python -m rsebench.cli generate-noise --profile configs/pilot/officeqa.yaml --limit 10 --offline
python -m rsebench.cli generate-noise --profile configs/pilot/docvqa.yaml --limit 10 --offline
```

Expected: every emitted artifact has a validation report and hash; failures/inapplicable cases remain visible.

- [ ] **Step 4: Run DeepSeek model checks and pilots only if the key is present**

Run: `python -m rsebench.cli provider-check --config configs/pilot/deepseek-v4-flash.yaml`

If ready, execute Pilot-A then Pilot-B. If missing, write `blocked_on_credentials` to `pilot-readiness.md` and include the exact `.env` field needed; do not substitute GPT-5.5 or another model.

- [ ] **Step 5: Write audit and readiness reports**

The reports list downloaded/rejected/missing assets, byte sizes, revisions, native baseline readiness, passed/failed operators, API status without key values, and next commands. Distinguish `downloaded`, `materialized`, `validated`, and `experiment-complete`.

- [ ] **Step 6: Final repository verification and commit**

Run: `git diff --check && git status --short`

Then:

```bash
git add README.md docs/reports
git commit -m "docs: report rsebench pilot readiness"
```

Expected: clean working tree after commit.

---

## Plan Self-Review

- Spec coverage for Phase 0–2: baseline/data pinning, split isolation, C1–C3 domain noise, C4 adapter contract, small-sample Pilot-A/B, operator gates, DeepSeek-only model profile, unified contracts, audit and freeze prerequisites are assigned to tasks.
- Deferred by design: RGSE implementation, full frozen benchmark generation, all-method full-data experiments, and Skill-native diagnostic runs. These begin only after pilot operators pass and receive a separate implementation plan.
- Type consistency: registry loaders, contracts, DeepSeek client, `NoiseOperator.generate`, domain validators, pilot manifests, and calibration decisions have one defined producer and named consumers.
- Secret policy: `.env` remains local and empty; no task reads or prints key values.
- Cost policy: model calls are cached, limited, and locked to `deepseek-v4-flash`.
