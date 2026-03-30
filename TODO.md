# TODO

## Next

- Improve question extraction so the LLM sees the real employer question instead of DOM noise.
- Add support for more questionnaire widgets, especially custom controls and multi-selects.
- Add Playwright smoke tests for search extraction, intro-page asset handling, questionnaire filling, and submit flow.
- Add optional screenshot capture on failed applications.

## Planned

- Move matching toward a hybrid approach first: keep deterministic signals, add semantic similarity, and preserve explainability in logs/CSV.
- Introduce structured LLM outputs gradually with Pydantic/instructor, starting with the lowest-risk paths before questionnaire and cover letter flows.
- Separate the LLM auto-accept threshold from the LLM memory-write policy so low-confidence edge cases do not get stored unintentionally.
- Evaluate whether the current global matching taxonomy should stay global or move to per-role keyword lists after more real application runs.
- Add embedding-based questionnaire memory reuse later instead of string-based fuzzy question matching.
- Replace the module-level LLM logger global with explicit dependency injection or a small LLM service object.
- Reintroduce a safe direct standard-answer bypass before the LLM, without bringing back the old loose regex-heavy matcher.

## Deferred

- More aggressive handling of prefilled employer-question answers. Current behavior intentionally leaves prefilled answers in place unless the page requires intervention.

## Out Of Scope For Now

- External/non-Quick Apply flows
