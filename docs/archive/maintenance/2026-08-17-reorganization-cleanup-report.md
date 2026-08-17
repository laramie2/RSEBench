# Repository reorganization cleanup report

> Completed: 2026-08-17 UTC

## Scope approved

The approved cleanup covered repository-local caches, generated test artifacts, two merged linked worktrees, and worktree-only historical evidence recovery. It did not authorize deletion of paid run evidence, candidate Git sources, candidate raw data, active materializations, or frozen release paths.

## Evidence recovered before deletion

- Copied the untracked OfficeQA/WebShop clean-v2 execution plan byte-for-byte to `docs/archive/implementation-plans/2026-08-14-officeqa-webshop-clean-v2-execution.md`.
- Copied the complete `.worktrees/rsebench-pilot/outputs/` tree to `outputs/archive/worktree-rsebench-pilot-20260817/`.
- The recovered output archive contains 10,130 files and occupies approximately 117 MB.
- Verified every archived file against the source tree; the normalized checksum ledger has 10,130 entries at `outputs/archive/2026-08-17-worktree-recovery/SHA256SUMS`.
- Restored six report-cited roots under their original `outputs/runs/` locators: expanded N1 aggregate, two Spreadsheet Core-1 runs, OfficeQA N4, WebShop N1 structural smoke, and SkillLearn N3 fixed smoke.
- Nine Docker-created XLSX files were owned by root with mode `0600`. A local existing container changed only their read mode to `0644`; file bytes were then hash-verified.
- The first incomplete copy was moved to the system trash after a complete replacement passed checksum verification.

## Removed paths and sizes

The following rebuildable paths were moved to the system trash:

| Path | Size before cleanup |
|---|---:|
| `.pytest_cache/` | 116 KB |
| `.ruff_cache/` | 108 KB |
| `pytest-of-nvidia/` | 14 MB |
| `src/rsebench.egg-info/` | 28 KB |
| `outputs/preflight/task7-stale/` | empty |
| `outputs/cache/model/` | 9.3 MB |
| `scripts/**/__pycache__/`, `src/**/__pycache__/`, `tests/**/__pycache__/` | 45 directories |

Two linked worktrees occupying approximately 168 MB were removed with `git worktree remove --force` after recovery verification:

```text
.worktrees/clean-qualification-fixes
.worktrees/rsebench-pilot
```

The worktree registry now contains only the primary checkout. The `.worktrees/` directory is empty.

Four temporary checksum-generation files were moved to trash after the canonical `SHA256SUMS` ledger was retained. The retained checksum directory occupies approximately 2.3 MB.

## Retained high-volume paths

| Path | Post-cleanup size | Reason retained |
|---|---:|---|
| `outputs/` | 1.5 GB | paid, frozen, historical and recovered run evidence |
| `data/` | 5.1 GB | active and candidate benchmark data |
| `methods/external/` | 6.8 GB | active and candidate upstream Git sources |
| `.venv/` | 364 MB | working project environment |

`outputs/` grew relative to the pre-cleanup snapshot because the complete worktree-only archive and six canonical report locators were intentionally recovered before the old worktree was removed.

## Frozen paths intentionally unchanged

- `configs/validation/validation-v1.yaml`
- `benchmark/datasets/*/*/releases/validation-v1/manifest.json`
- `benchmark/validation/clean_qualification_v2/`
- `benchmark/validation/skillflow_clean_qualification_v1/`
- `methods/validated/*/releases/`
- the four SkillFlow evidence roots recorded in `noise_validation_selection.json`

No release ID, content hash, operator ID, provider setting, task ID, seed or runtime budget was changed by cleanup.

## Git branches retained

The source branches remain available:

```text
feature/rsebench-pilot at 6fb608c
fix/clean-qualification-baselines at 3795c23
```

Both are ancestors of `main` at cleanup time.

## Recovery procedure

Recreate a source worktree from a retained branch if needed:

```bash
git worktree add .worktrees/rsebench-pilot-recovery feature/rsebench-pilot
git worktree add .worktrees/clean-qualification-recovery fix/clean-qualification-baselines
```

Historical output bytes are recovered from `outputs/archive/worktree-rsebench-pilot-20260817/` and verified with `outputs/archive/2026-08-17-worktree-recovery/SHA256SUMS`. Cache paths were moved to the desktop trash and are also reproducible from tests or preflight commands.

## Verification results

- Worktree-only execution plan: byte-identical copy.
- Full recovered output archive: 10,130/10,130 file checksums matched.
- Six report-cited output locators: present.
- Historical branch ancestry: both merged branches confirmed.
- Python editable import after worktree removal: resolves to primary `src/rsebench/__init__.py`.
- Paid provider calls during recovery and cleanup: 0.
