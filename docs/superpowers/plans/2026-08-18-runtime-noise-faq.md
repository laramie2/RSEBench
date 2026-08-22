# Runtime-noise FAQ Implementation Plan

> **N4 portions superseded (2026-08-21).** 本文保留历史实施记录；当前 N4 以 [Update-Evidence Misbinding 交接方案](../../architecture/2026-08-21-n4-update-evidence-misbinding-handoff.md) 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a Chinese N3/N4 FAQ and connect it to the three current documentation entry points.

**Architecture:** Keep conceptual explanation in one standalone FAQ while leaving the normative interface in `noise-stage-interface.md`. Add short relative links from the documentation index, onboarding guide, and protocol so collaborators can move between explanation and specification without duplicating definitions.

**Tech Stack:** Markdown, repository-relative links, pytest for the nearest existing documentation-link regression test, and a repository-wide local-link scan.

## Global Constraints

- N3 and N4 remain independent experiment arms; the FAQ must not describe N3+N4 composition as validation-v1 behavior.
- Protected execution outcomes remain immutable.
- N3/N4 belong to RSEBench as executable benchmark-suite components, not static dataset artifacts.
- A method without a faithful feedback boundary must report N4 as unsupported, not as a null effect.
- Existing operator IDs, release identities, protected fields, and matrix definitions remain unchanged.

---

### Task 1: Publish the runtime-noise FAQ and navigation links

**Files:**
- Create: `docs/qa/runtime-noise-faq.md`
- Modify: `docs/README.md`
- Modify: `docs/project-onboarding.md`
- Modify: `docs/protocols/noise-stage-interface.md`

**Interfaces:**
- Consumes: the stage boundaries and protected fields defined in `docs/protocols/noise-stage-interface.md`.
- Produces: the stable conceptual entry point `docs/qa/runtime-noise-faq.md`, referenced by all three navigation files.

- [ ] **Step 1: Create the FAQ with the approved conceptual contract**

Use these exact top-level sections:

```markdown
# N3/N4 运行时加噪常见问题

## 1. N1/N2 与 N3/N4 的区别是什么？
## 2. N3 和 N4 分别修改什么？
## 3. N3/N4 是否属于 RSEBench benchmark？
## 4. 为什么 N3/N4 会影响自进化？
## 5. 新 baseline 和新 benchmark 如何接入？
## 6. 如何让自研 pipeline 与 N3/N4 完全解耦？
## 7. 其他自进化工作如何使用 RSEBench？
## 8. 哪些情况不能解释为噪声无效？
```

The body must include the student-learning analogy, one concrete N3 example, one concrete N4 example, the `Method Adapter + Benchmark Policy + Stage Operator` decomposition, identity middleware pseudocode, capability negotiation for N4, and the `Initial/Clean/N1/N2/N3/N4` external evaluation protocol.

- [ ] **Step 2: Add the FAQ to the documentation index**

Under `docs/README.md` section `新协作者入口`, add:

```markdown
- [N3/N4 运行时加噪 FAQ](../../qa/runtime-noise-faq.md)
```

- [ ] **Step 3: Add the conceptual companion to onboarding**

Immediately after the concise N1–N4 definition in `docs/project-onboarding.md`, add a short paragraph linking to `qa/runtime-noise-faq.md` and stating that the FAQ explains runtime evidence, extension, and external evaluation.

- [ ] **Step 4: Add the conceptual companion to the normative protocol**

Near the introduction of `docs/protocols/noise-stage-interface.md`, add a link to `../qa/runtime-noise-faq.md` and state that the current protocol remains the normative implementation source.

- [ ] **Step 5: Review the content boundaries**

Confirm that the FAQ contains no new operator ID, release ID, stage composition, or protected-field rule that conflicts with `configs/validation/validation-v1.yaml` or `docs/protocols/noise-stage-interface.md`.

### Task 2: Verify and commit the documentation integration

**Files:**
- Verify: `docs/qa/runtime-noise-faq.md`
- Verify: `docs/README.md`
- Verify: `docs/project-onboarding.md`
- Verify: `docs/protocols/noise-stage-interface.md`
- Test: `tests/validation/test_validation_release_audit.py`

**Interfaces:**
- Consumes: the four Markdown changes from Task 1.
- Produces: a committed FAQ with resolving local links and no placeholder language.

- [ ] **Step 1: Scan for incomplete text**

Run:

```bash
rg -n "TBD|TODO|PLACEHOLDER|FIXME" docs/qa/runtime-noise-faq.md docs/README.md docs/project-onboarding.md docs/protocols/noise-stage-interface.md
```

Expected: no matches.

- [ ] **Step 2: Run the targeted documentation regression test**

Run:

```bash
pytest -q tests/validation/test_validation_release_audit.py
```

Expected: all tests pass.

- [ ] **Step 3: Verify repository-local Markdown links**

Run the repository local-link checker against current non-archived Markdown files and resolve every missing target. Expected: zero missing local targets.

- [ ] **Step 4: Check formatting and scope**

Run:

```bash
git diff --check
git diff --stat
```

Expected: no whitespace errors; the implementation diff contains one new FAQ and three navigation files.

- [ ] **Step 5: Commit**

```bash
git add docs/qa/runtime-noise-faq.md docs/README.md docs/project-onboarding.md docs/protocols/noise-stage-interface.md
git commit -m "docs: explain runtime evidence noise"
```
