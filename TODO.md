# TODO

## Next

- Extend widget adapters beyond native controls, especially richer custom combobox/button-based controls.
- Add Playwright smoke tests for search extraction, intro-page asset handling, questionnaire filling, and submit flow.
- Add optional screenshot capture on failed applications.

## Planned

- Tune the hybrid semantic matcher: weights, thresholds, model choice, and better explanation signals in logs/CSV.
- Preserve top-end semantic discrimination for resume ranking:
  - keep a floor to suppress random cosine noise
  - stop capping high-end cosine values for selection
  - if needed, separate display normalization from ranking normalization so strong-vs-strong resume differences are not flattened away
- Expand LangGraph from per-job orchestration to explicit run-level orchestration with named run states such as:
  - initialize run
  - open search page
  - collect job cards
  - pick next job
  - process job
  - paginate
  - finish run
- Add checkpointed run-state persistence so interrupted runs can resume from the last known search page, job index, and run state.
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
- Expand the DB-backed eval report beyond the initial `scripts/eval_report.py` query set when patterns emerge.
- Add explicit provider-level routing and cost controls so local vs hosted models can be selected by task type and scarce hosted credits can be reserved for questionnaire answering only.
- Persist human-in-the-loop checkpoints explicitly so low-confidence or sensitive questions can pause and resume as first-class workflow state instead of only relying on terminal prompts.
- Document and handle the first-run cold-start state where `qa_memory` is empty and questionnaire answering has no prior verified memory yet.

## Deferred

- More aggressive handling of prefilled employer-question answers. Current behavior intentionally leaves prefilled answers in place unless the page requires intervention.

## Out Of Scope For Now

- External/non-Quick Apply flows
