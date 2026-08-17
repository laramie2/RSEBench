# DeepSeek API Baselines and Paired Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt every runnable baseline to DeepSeek V4 Flash API execution, verify the paths with graded smoke tests, and run paired clean/noisy self-evolution pilots on SpreadsheetBench-Verified, OfficeQA, and DAPO with evaluation on one frozen clean test set.

**Architecture:** `rsebench` owns provider capabilities, safe tool execution, adapter metadata, immutable experiment manifests, and paired metrics. Baseline-specific launchers preserve native training/evolution code and translate only model configuration, task manifests, skill artifacts, and result records. Exact requests are cached, every run is append-only, and clean-test data is isolated from all update and selection paths.

**Tech Stack:** Python 3.11+, Pydantic 2, OpenAI-compatible DeepSeek API, Typer, PyYAML, pandas/pyarrow, pytest, baseline-specific virtual environments, Docker/Harbor for SkillFlow/FederatedSkill.

## Global Constraints

- The only online model is exactly `deepseek-v4-flash` at `https://api.deepseek.com`.
- Read credentials only from `/home/nvidia/yutao/lzt/self-evolution-robustness/.env`; never persist or print them.
- Use explicit non-thinking mode unless a role-specific experiment is separately approved.
- Never fall back to another model or provider.
- Preserve baseline algorithms and official benchmark evaluators.
- Both arms start from byte-identical seed skills and use identical task IDs, split membership, order, method seed, model settings, budgets, and iteration count.
- Inject noise only into evolution-train and evolution-validation; evaluate both arms on the same untouched clean-test set.
- Follow red-green-refactor for every production-code change.

---

### Task 1: Provider Capability Contract

**Files:**
- Create: `src/rsebench/providers/contracts.py`
- Modify: `src/rsebench/providers/deepseek.py`
- Modify: `src/rsebench/providers/__init__.py`
- Test: `tests/providers/test_deepseek_capabilities.py`

**Interfaces:**
- Produces: `ToolCall(id: str, name: str, arguments: dict[str, Any])`.
- Produces: `ModelResponse.content`, `ModelResponse.tool_calls`, `ModelResponse.usage`, `ModelResponse.finish_reason`, and `ModelResponse.cache_hit`.
- Extends: `DeepSeekClient.complete(..., tools=None, tool_choice=None, role="target")`.
- Preserves: all existing call sites that omit the new arguments.

- [ ] **Step 1: Write failing tests for tool-call parsing and role-isolated cache keys**

```python
def test_tool_call_response_is_normalized(tmp_path, monkeypatch):
    client = fake_deepseek_client(tmp_path, monkeypatch, tool_name="read_text")
    response = client.complete(
        [{"role": "user", "content": "read it"}],
        tools=[READ_TOOL],
        role="executor",
    )
    assert response.tool_calls[0].name == "read_text"
    assert response.tool_calls[0].arguments == {"path": "note.txt"}


def test_cache_key_isolated_by_role(tmp_path):
    client = DeepSeekClient.for_test(tmp_path)
    messages = [{"role": "user", "content": "x"}]
    assert client.request_cache_key(messages, role="target") != client.request_cache_key(
        messages, role="optimizer"
    )
```

- [ ] **Step 2: Run the tests and confirm failure because the capability fields do not exist**

Run: `pytest -q tests/providers/test_deepseek_capabilities.py`

Expected: FAIL on the missing `tool_calls` field or unsupported `role` argument.

- [ ] **Step 3: Implement typed tool calls, request fields, response normalization, cache isolation, and redacted failures**

The cache payload must contain no API key and must include the exact locked model,
role, tools, response format, thinking mode, and generation limits in its hash.

- [ ] **Step 4: Run provider and legacy tests**

Run: `pytest -q tests/providers tests/test_experiments.py tests/test_generation.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/providers tests/providers
git commit -m "feat: add deepseek provider capabilities"
```

### Task 2: Safe DeepSeek Tool Agent

**Files:**
- Create: `src/rsebench/agents/__init__.py`
- Create: `src/rsebench/agents/tool_agent.py`
- Test: `tests/agents/test_tool_agent.py`

**Interfaces:**
- Produces: `ToolAgentConfig(workspace_root: Path, max_turns: int, command_timeout_seconds: float, max_output_chars: int)`.
- Produces: `ToolAgentResult(final_text: str, turns: int, tool_calls: int, errors: list[str])`.
- Produces: `DeepSeekToolAgent(client, config).run(instruction: str, system: str = "")`.
- Tools: `list_files`, `read_text`, `write_text`, and `run_command` with argv lists and relative working directories.

- [ ] **Step 1: Write failing containment and tool-loop tests**

```python
def test_read_rejects_path_escape(tmp_path):
    agent = fixture_agent(tmp_path)
    with pytest.raises(ValueError, match="outside workspace"):
        agent.execute_tool("read_text", {"path": "../secret"})


def test_agent_executes_tool_then_returns_final_text(tmp_path):
    client = scripted_client(tool_call("write_text", {"path": "x.txt", "content": "ok"}), final("done"))
    result = DeepSeekToolAgent(client, ToolAgentConfig(workspace_root=tmp_path)).run("write x")
    assert (tmp_path / "x.txt").read_text() == "ok"
    assert result.final_text == "done"
```

- [ ] **Step 2: Run and confirm the tests fail because the agent package is missing**

Run: `pytest -q tests/agents/test_tool_agent.py`

- [ ] **Step 3: Implement the minimal bounded tool loop**

Use `subprocess.run(argv, shell=False, cwd=contained_path, timeout=...)`; truncate
tool observations; reject absolute paths, `..` escapes, symlink escapes, empty argv,
and commands whose executable is not in the configured allowlist.

- [ ] **Step 4: Run tool-agent and provider tests**

Run: `pytest -q tests/agents tests/providers`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/agents tests/agents
git commit -m "feat: add bounded deepseek tool agent"
```

### Task 3: Adapter Registry and Smoke Contracts

**Files:**
- Create: `benchmark/registry/adapters.yaml`
- Create: `src/rsebench/adapters/__init__.py`
- Create: `src/rsebench/adapters/contracts.py`
- Create: `src/rsebench/adapters/registry.py`
- Create: `src/rsebench/adapters/smoke.py`
- Modify: `src/rsebench/cli.py`
- Test: `tests/adapters/test_registry.py`
- Test: `tests/adapters/test_smoke.py`

**Interfaces:**
- Produces: `SmokeLevel = transport | structured | tool | native_task | evolution`.
- Produces: `BaselineAdapterSpec` with upstream commit, role mapping, commands, artifact paths, and scorer.
- Produces: `SmokeRecord(method, level, status, model, run_dir, detail, evidence)`.
- CLI: `rsebench baseline-smoke --method <name> --through <level>`.

- [ ] **Step 1: Write failing registry completeness and stop-on-failure tests**

```python
def test_registry_lists_every_runnable_method():
    assert set(load_adapter_registry().adapters) == {
        "trace2skill", "skillopt", "skillgrad", "evoskill",
        "skills_coach", "skillflow", "federatedskill",
    }


def test_smoke_stops_after_first_failed_level(fake_adapter):
    record = run_smoke(fake_adapter, through="evolution")
    assert [x.level for x in record.levels] == ["transport", "structured"]
    assert record.status == "failed"
```

- [ ] **Step 2: Run and observe missing-registry failures**

Run: `pytest -q tests/adapters/test_registry.py tests/adapters/test_smoke.py`

- [ ] **Step 3: Implement strict registry parsing, append-only run records, and CLI**

Registry commands must reference method virtual-environment executables explicitly
and must never interpolate an API key into a command string.

- [ ] **Step 4: Validate registry and tests**

Run: `pytest -q tests/adapters tests/test_registry.py`

- [ ] **Step 5: Commit**

```bash
git add benchmark/registry/adapters.yaml src/rsebench/adapters src/rsebench/cli.py tests/adapters
git commit -m "feat: add baseline smoke registry"
```

### Task 4: Native OpenAI-Compatible Baselines

**Files:**
- Create: `scripts/baselines/common_env.py`
- Create: `scripts/baselines/smoke_trace2skill.py`
- Create: `scripts/baselines/smoke_skillopt.py`
- Create: `scripts/baselines/smoke_skillgrad.py`
- Create: `configs/baselines/trace2skill.yaml`
- Create: `configs/baselines/skillopt.yaml`
- Create: `configs/baselines/skillgrad.yaml`
- Test: `tests/adapters/test_native_baselines.py`

**Interfaces:**
- Produces: `deepseek_role_env(method: str, role: str) -> dict[str, str]` without mutating the parent environment.
- Each smoke script supports `--level`, `--output`, and `--offline-fixture`.
- Each script writes one `SmokeRecord` JSON and exits nonzero on task/evolution failure.

- [ ] **Step 1: Write failing tests for exact model/endpoint mapping and secret-free output**
- [ ] **Step 2: Run `pytest -q tests/adapters/test_native_baselines.py` and confirm failure**
- [ ] **Step 3: Implement Trace2Skill, SkillOpt, and SkillGrad role mappings and smoke launchers**
- [ ] **Step 4: Run fixture smokes, then real transport/structured/tool smokes with the project `.env`**

Run:

```bash
python scripts/baselines/smoke_trace2skill.py --level tool --output outputs/smoke/trace2skill
python scripts/baselines/smoke_skillopt.py --level tool --output outputs/smoke/skillopt
python scripts/baselines/smoke_skillgrad.py --level tool --output outputs/smoke/skillgrad
```

Expected: every record reports model `deepseek-v4-flash`, no secret text, and zero
transport/tool errors.

- [ ] **Step 5: Run one native clean task and one bounded evolution update per method**
- [ ] **Step 6: Commit main-project launchers and configs**

### Task 5: EvoSkill Direct API Harness

**Files:**
- Create: `src/rsebench/adapters/evoskill.py`
- Create: `scripts/baselines/smoke_evoskill.py`
- Create: `adapters/evoskill/deepseek_api.patch`
- Create: `configs/baselines/evoskill.yaml`
- Test: `tests/adapters/test_evoskill.py`

**Interfaces:**
- Patch adds EvoSkill harness name `deepseek_api` and delegates execution to the shared bounded tool agent.
- Produces OfficeQA and DAPO CSV predictions in EvoSkill's existing scorer format.
- Patch base commit must equal `36f6f04952293d7054145550c2b9f0b0411bff1c`.

- [ ] **Step 1: Write a failing patch/registry fixture test**
- [ ] **Step 2: Confirm failure because `deepseek_api` is absent**
- [ ] **Step 3: Implement and export a reproducible patch without changing EvoSkill evolution selection logic**
- [ ] **Step 4: Run transport, structured, tool, OfficeQA clean-task, and 2-example evolution smoke**
- [ ] **Step 5: Run one DAPO clean-task adapter smoke**
- [ ] **Step 6: Commit**

### Task 6: Skills-Coach API Adaptation

**Files:**
- Create: `src/rsebench/adapters/skills_coach.py`
- Create: `scripts/baselines/smoke_skills_coach.py`
- Create: `adapters/skills_coach/deepseek_api.patch`
- Create: `configs/baselines/skills-coach.yaml`
- Test: `tests/adapters/test_skills_coach.py`

**Interfaces:**
- Routes generator, optimizer, executor, and judge roles through the locked provider.
- Uses the baseline's generated-task verifier and produces its native optimized-skill artifact.

- [ ] **Step 1: Write failing role-coverage and secret-redaction tests**
- [ ] **Step 2: Confirm failures**
- [ ] **Step 3: Implement patch and launcher**
- [ ] **Step 4: Run five smoke levels on the smallest native generated-task fixture**
- [ ] **Step 5: Commit**

### Task 7: SkillFlow and FederatedSkill Harbor API Agents

**Files:**
- Create: `src/rsebench/adapters/harbor_agent.py`
- Create: `scripts/baselines/smoke_skillflow.py`
- Create: `scripts/baselines/smoke_federatedskill.py`
- Create: `adapters/skillflow/deepseek_api.patch`
- Create: `adapters/federatedskill/deepseek_api.patch`
- Create: `configs/baselines/skillflow.yaml`
- Create: `configs/baselines/federatedskill.yaml`
- Test: `tests/adapters/test_harbor_agent.py`

**Interfaces:**
- `DeepSeekHarborAgent` binds provider tool calls to the Harbor environment terminal API.
- FederatedSkill uses the same worker and a DeepSeek cloud-merger role.
- SkillFlow Harbor is pinned to commit `ab6c8f07914f3f4c24b52377475d90f506103844` until the upstream runner is migrated.

- [ ] **Step 1: Write failing fake-Harbor action-loop and merger-role tests**
- [ ] **Step 2: Confirm failures**
- [ ] **Step 3: Implement shared Harbor agent and reproducible patches**
- [ ] **Step 4: Run offline fake-environment tests and one real SkillFlow task smoke**
- [ ] **Step 5: Run one bounded iterative SkillFlow update**
- [ ] **Step 6: Run FederatedSkill transport/tool smoke, then one two-worker one-round smoke**
- [ ] **Step 7: Commit**

### Task 8: Immutable Paired Split and Run Manifests

**Files:**
- Create: `src/rsebench/evolution/contracts.py`
- Create: `src/rsebench/evolution/pairs.py`
- Create: `src/rsebench/evolution/splits.py`
- Create: `tests/evolution/test_pairs.py`
- Create: `tests/evolution/test_splits.py`

**Interfaces:**
- Produces: `EvolutionTaskPair(pair_id, task_id, clean, noisy, noise_id)`.
- Produces: `EvolutionSplitManifest(train, validation, clean_test, seed, source_hash)`.
- Produces: `assert_arm_equivalence(clean_manifest, noisy_manifest)` excluding only permitted noisy payload hashes.

- [ ] **Step 1: Write failing tests for pair identity, group isolation, and clean-test immutability**
- [ ] **Step 2: Confirm failures**
- [ ] **Step 3: Implement manifests and deterministic split generation**
- [ ] **Step 4: Run evolution manifest tests and existing split tests**
- [ ] **Step 5: Commit**

### Task 9: Evolution-Timed Noise Generation for Three Domains

**Files:**
- Modify: `src/rsebench/generation.py`
- Modify: `src/rsebench/domains/math.py`
- Modify: `src/rsebench/prompts/math_noise.py`
- Create: `configs/evolution/spreadsheet.yaml`
- Create: `configs/evolution/officeqa.yaml`
- Create: `configs/evolution/math.yaml`
- Create: `tests/evolution/test_noise_generation.py`

**Interfaces:**
- All generated manifests use `timing=evolution`.
- Input is one frozen split manifest; output is one paired manifest plus accepted/rejected records.
- Math outputs must pass answer-leak, exactly-one-error, JSON, and two-critic consensus checks.

- [ ] **Step 1: Write failing timing, test-isolation, and hard-gate tests**
- [ ] **Step 2: Confirm failures**
- [ ] **Step 3: Implement profile-driven paired generation without transforming clean-test**
- [ ] **Step 4: Run fixture generation tests**
- [ ] **Step 5: Generate ten-task feasibility batches for all three domains with DeepSeek only where required**
- [ ] **Step 6: Commit accepted implementation and immutable run references**

### Task 10: Paired Evolution Orchestrator and Metrics

**Files:**
- Create: `src/rsebench/evolution/runner.py`
- Create: `src/rsebench/evolution/metrics.py`
- Create: `src/rsebench/evolution/report.py`
- Modify: `src/rsebench/cli.py`
- Create: `tests/evolution/test_runner.py`
- Create: `tests/evolution/test_metrics.py`

**Interfaces:**
- CLI: `rsebench paired-evolution --method <m> --profile <yaml> --operator <op> --seed <n>`.
- Produces seed, clean-arm, and noisy-arm skill hashes and clean-test scores.
- Produces `clean_gain`, `noisy_gain`, `evolution_gap`, reverse-evolution flag, API/tool failure diagnostics, and paired bootstrap interval.

- [ ] **Step 1: Write failing tests proving identical arm inputs and clean-test exclusion**
- [ ] **Step 2: Write failing metric tests with known scores**
- [ ] **Step 3: Confirm failures**
- [ ] **Step 4: Implement append-only orchestration and metrics**
- [ ] **Step 5: Run fixture paired experiments**
- [ ] **Step 6: Commit**

### Task 11: Online Baseline Smoke Matrix

**Files:**
- Create: `scripts/run/baseline_smokes.sh`
- Create: `docs/reports/baseline-api-smoke-status.md`

**Interfaces:**
- Script runs every adapter serially, stops each method at its first failed level,
  and never stops unrelated methods.
- Report links every machine-readable smoke record and names the exact blocker.

- [ ] **Step 1: Run the complete offline suite**
- [ ] **Step 2: Run all seven online smoke ladders using the project `.env`**
- [ ] **Step 3: Inspect scorer outputs, skill hashes, method commits, model IDs, and secret scan**
- [ ] **Step 4: Write and commit the evidence-backed smoke matrix**

### Task 12: Three-Domain Paired Validation Pilots

**Files:**
- Create: `configs/experiments/spreadsheet-paired-pilot.yaml`
- Create: `configs/experiments/officeqa-paired-pilot.yaml`
- Create: `configs/experiments/math-paired-pilot.yaml`
- Create: `scripts/run/paired_pilots.sh`
- Create: `docs/reports/paired-evolution-pilot-results.md`

**Interfaces:**
- Executes one operator at a time for two seeds.
- Starts with 20 train / 10 validation / 30 clean-test tasks where available.
- Uses only methods whose domain-specific smoke level 5 passed.

- [ ] **Step 1: Screen and freeze common clean-solvable task subsets**
- [ ] **Step 2: Persist split, pair, and seed-skill hashes before any evolution run**
- [ ] **Step 3: Run SpreadsheetBench clean/noisy evolution arms for Trace2Skill, SkillOpt, and SkillGrad**
- [ ] **Step 4: Run OfficeQA arms for SkillOpt and EvoSkill**
- [ ] **Step 5: Run DAPO arms for SkillOpt and EvoSkill only if clean evolution gain is positive**
- [ ] **Step 6: Evaluate every produced skill on the same frozen clean-test set**
- [ ] **Step 7: Compute evolution gaps, bootstrap intervals, reverse-evolution flags, and failure diagnostics**
- [ ] **Step 8: Accept, reject, or redesign each operator without post-hoc task deletion**
- [ ] **Step 9: Run full tests, `git diff --check`, secret scan, and manifest hash audit**
- [ ] **Step 10: Commit the pilot report and reproducible configs**
