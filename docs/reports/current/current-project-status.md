# RSEBench current project status

> Status date: 2026-08-17 UTC
>
> Scope: validation-v1 mechanism-validation release and the next executable gate

## Current conclusion

Validation-v1 has frozen four DatasetRelease identities, four active MethodRelease profiles, four independent noise-stage interfaces, and an exact 4×4 matrix of 16 noisy cells. Attempt isolation, release-specific patch replay, scheduler, CLI, aggregation contracts, and token/timing infrastructure are implemented.

Concrete stage `CELL_RUNNERS` are still interface-only. Provider-free preflight can validate structure and local artifacts but reports `execution_ready=false`; no new formal N1–N4 paid run has started and provider calls remain 0.

## Frozen datasets

| Domain | DatasetRelease | Scale | Clean evidence boundary |
|---|---|---:|---|
| Spreadsheet | `spreadsheetbench-verified-validation-v1` | 20/10/30 | selected control `0.3333→0.4333`; historical seeds include no-update/regression |
| Document | `officeqa-full-validation-v1` | 12/12/20 | complete update with score tie `0.65→0.65` |
| Interactive | `webshop-validation-v1` | 5/5/20 | selected control `0.1025→0.30`; relatively high per-run cost |
| Skill | `skillflow-tasks-validation-v1` | 3 families × 6 | HWPX local positive signal; Distribution/Embedded execution-update ties |

These inputs support controlled mechanism comparison. They do not establish a strong claim that clean self-evolution is stable and positive across all four domains.

## Active method profiles

| Domain | MethodRelease | Status |
|---|---|---|
| Spreadsheet | `skillopt-spreadsheet-validation-v1` | active, four-patch profile |
| Document | `skillopt-officeqa-validation-v1` | active, five-patch profile |
| Interactive | `skilladaptor-webshop-validation-v1` | active |
| Skill | `skillflow-validation-v1` | active |

SkillLearn Self-Feedback release `skilllearn-self-feedback-diagnostic-v1` remains `validated_inactive` and is retained only as historical diagnostic evidence.

## Infrastructure verification

- 16 structural matrix cells expand successfully.
- 139 local artifact locators have been validated.
- Four active MethodRelease patch series replay from their pinned upstream revisions.
- Every attempt uses an isolated directory and immutable identity checks.
- Provider-free preflight makes 0 model calls.
- Timing and token contracts cover run, cell/attempt, and provider-call levels.

## Current blockers

| Stage | Missing executable component |
|---|---|
| N1 | four benchmark-specific task-context operators and static runners |
| N2 | immutable clean/noisy evidence materialization and static runners |
| N3 | method-specific trajectory selector/operator adapters |
| N4 | method-specific feedback/update-boundary adapters |

The next shared gate is one provider-free executable cell for each stage. Only after those four cells pass protected-field, applicability, release, and replay checks should bounded paid validation begin.

## Current entry points

- [Validation-v1 matrix](../../../configs/validation/validation-v1.yaml)
- [Validation-v1 freeze report](2026-08-17-validation-v1-freeze.md)
- [N1–N4 progress dashboard](../../progress/README.md)
- [Project roadmap](../../project-roadmap.md)
- [Validation architecture](../../architecture/validation-v1-architecture.md)
- [Validation runbook](../../operations/validation-runbook.md)
- [Historical experiment registry](../../archive/experiment-history/registry.yaml)
