# Clean v1 Diagnostic Archive

Date: 2026-08-14

This stopped matrix is retained as diagnostic evidence only. It is not a
formal clean release and cannot unlock N1–N4.

| Cell | Completed evidence | Diagnostic conclusion |
|---|---|---|
| SpreadsheetBench-Verified / SkillOpt | Three seeds; clean gains `+0.0667`, `+0.1333`, `0.0` | Two seeds updated and improved; the cell showed effective clean evolution. |
| OfficeQA / SkillOpt | Three seeds; zero accepted updates | Runtime/recovery and validation issues invalidated the cell. |
| WebShop / SkillAdaptor | Two invalid positive gains (`+0.20`, `+0.05`) and one crash | ID, action parsing, and Linker JSON paths require v2 reruns. |
| SkillLearn / organize-messy-files | Three seeds, two accepted updates each, all `0.0 -> 0.0` | Execution worked but efficacy was absent. |
| SkillLearn / offer-letter-generator | One completed seed at `0.3333 -> 0.3333`; the next seed was interrupted | The partial family result is non-formal and showed no gain. |

The matrix persisted 12 completed units and one failed WebShop unit before it
was manually stopped during the next SkillLearn unit. The interrupted unit has
no `result.json` and is not counted.

Token accounting observed all 17,355 calls. Billed usage was 36,966,696 prompt
tokens and 3,257,418 completion tokens, for 40,224,114 total tokens.

The content-addressed diagnostic manifest is stored at
`releases/diagnostic/clean-v1-pilot/manifest.json`. Its run locator is portable;
the raw result tree remains local and gitignored.
