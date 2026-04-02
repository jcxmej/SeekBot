# TODO

## Next

- Improve question extraction so the LLM sees the real employer question instead of DOM noise.
- Broaden questionnaire widget support, especially richer custom controls beyond native inputs/selects.
- Add Playwright smoke tests for search extraction, intro-page asset handling, questionnaire filling, and submit flow.
- Add optional screenshot capture on failed applications.
- Clean up the redundant questionnaire event duplication between generic run logs and `qa_memory`.

## Planned

- Tune the hybrid semantic matcher: weights, thresholds, model choice, and better explanation signals in logs/CSV.
- Extend the Postgres storage layer to cover:
  - structured run/LLM event tables
  - persisted debug prompt artifacts when useful
- Continue using `pgvector` for semantic Q&A memory retrieval instead of adding ChromaDB.
- Keep the storage abstraction boundary clean:
  - Playwright layers should still talk to `JobStore` / `QuestionStore` style interfaces
  - database access should stay behind the storage layer
- Separate the LLM auto-accept threshold from the LLM memory-write policy so low-confidence edge cases do not get stored unintentionally.
- Evaluate whether the current global matching taxonomy should stay global or move to per-role keyword lists after more real application runs.
- Add embedding-based questionnaire memory reuse later instead of string-based fuzzy question matching.
- Replace the module-level LLM logger global with explicit dependency injection or a small LLM service object.
- Add DB-backed eval queries instead of introducing a separate `seekbot_evals.csv`.
- Add explicit provider-level cost controls and feature toggles so scarce hosted credits can be reserved for questionnaire answering only.

## Deferred

- More aggressive handling of prefilled employer-question answers. Current behavior intentionally leaves prefilled answers in place unless the page requires intervention.
- Full LangGraph orchestration rewrite. Valuable, but after the storage/questionnaire foundations are more stable.

## Out Of Scope For Now

- External/non-Quick Apply flows
