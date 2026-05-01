# Decisions

This file records the current project decisions, constraints, and deferred ideas so they do not live only in chat history.

## Current Runtime Scope

- SeekBot currently supports **Seek Quick Apply only**.
- External apply flows and non-Quick Apply flows are out of scope for the active runtime.
- One configured LLM provider is used per run. There is no in-run provider fallback/orchestration layer.
- The outer search-page loop remains simple and imperative.
- Individual job processing now runs through a LangGraph state machine.

## Configuration

- The loader only tries:
  1. `seek_config_local`
  2. `seek_config`
- `seek_config.py` is the public template.
- `seek_config_local.py` is the private local override and is ignored by git.
- Storage now defaults to local Postgres.
- CSV persistence remains as fallback only when Postgres is not configured or unavailable.

## Matching

- Resume matching is currently semantic-first and JD-led.
- Matching uses local `sentence-transformers` embeddings for scoring.
- Matching still uses a single global technical taxonomy for keyword explanations and logs.
- Resume selection compares the JD against every configured resume.
- Resume selection uses three signals:
  - hybrid JD/resume compatibility
  - search-role stickiness
  - job-title alignment
- Job-title alignment should only influence selection when the title gives a meaningful signal.
- If the title does not clearly align to any configured resume role, the selector should fall back to search-role stickiness plus hybrid compatibility.
- Compatibility score and resume-selection score are separate and should be logged separately.
- Matching is intentionally not LLM-scored at runtime right now.
- Per-role taxonomies are deferred for later evaluation.

## LLM Behavior

- The default active local model is currently `qwen3:8b` on Ollama.
- Hugging Face using `deepseek-ai/DeepSeek-V3-0324` remains available as a hosted provider when needed.
- Resume text is always sent in full to the LLM. Resume truncation is intentionally removed.
- `question_issue` is a debug signal only. It should be logged, but it must not block answering by itself.
- The LLM layer now uses schema-validated structured generation with Pydantic models and `instructor`.
- The current structured models are:
  - `QuestionAnswer`
  - `CoverLetter`
  - `ContactExtraction`
- The module-level LLM logger global is accepted for now as a V1 shortcut, but should be replaced later.
- The old global LLM disable flag was removed. A failed LLM call should fail that call only, not disable later LLM usage in the same run.

## Employer Question Flow

- Current answer priority is:
  1. exact verified memory
  2. similar verified memory
  3. LLM from resume plus verified prior Q&A context
  4. user if confidence is too low
- The questionnaire-answering prompt should not use the JD. It should use the resume plus verified prior Q&A memory only.
- Questionnaire extraction is now block-first:
  - start from visible controls
  - group them into question blocks
  - extract one clean question and option set per block
  - answer/apply once per block
- Only answers with `confidence > 0.85` should be auto-accepted.
- Answers with `confidence <= 0.85` should prompt the user.
- Verified memory means a human accepted or provided the answer.
- Exact verified memory auto-reuses directly.
- Similar verified memory may auto-apply when its confidence is above the active threshold. Otherwise it should be presented to the user for confirmation.
- Native multi-select questions should use a dedicated multi-option LLM prompt and apply every supported option the model returns.
- Block-first extraction reduces DOM noise substantially, but some custom widgets can still need explicit adapters.
- The old static `question_answers` questionnaire dictionary is removed from the active questionnaire flow.
- This means a fresh install with empty `qa_memory` starts from a colder state: early questionnaire answers rely on the resume until verified memory is built through use.
- Questionnaire memory may store unverified LLM answers as the latest state for that exact canonical question, but read paths must stay restricted to verified rows for direct reuse and trusted prompt context.
- String-based fuzzy memory reuse was intentionally removed as an auto-answer path. If non-exact memory reuse expands later, it should stay confirmation-gated and eventually use embeddings rather than lexical fuzzy matching.

## Storage

- Jobs and Q&A memory are moving behind a Postgres-backed storage layer.
- Jobs and Q&A memory are now primarily stored in Postgres, with CSV retained only as fallback/bootstrap.
- The primary storage path should stay behind the existing store-style boundary, not leak into Playwright/browser code.
- Existing CSV files are retained as fallback/bootstrap sources, not as the preferred runtime store.
- CSV bootstrap into Postgres should be configurable so intentionally clean database tests are possible without automatic legacy import.
- The Q&A memory store records the final answer actually applied or observed on the page, not every intermediate guess.
- `qa_memory` is the canonical questionnaire state store. Generic run logs should not duplicate questionnaire rows.
- Only verified answers should be reused directly or included as trusted Q&A context for the LLM.
- Low-confidence edge cases still need a cleaner separation between:
  - auto-accept threshold
  - memory-write policy
- The current V2 storage direction is local Postgres plus `pgvector`.
- Current state:
  - jobs are stored in the `jobs` table
  - Q&A memory is stored in the `qa_memory` table with embeddings
  - logs and debug prompt artifacts are still file-based for now
- `pgvector` is the intended semantic-memory path. ChromaDB is not the preferred next step right now.
- The storage boundary should remain clean:
  - Playwright/browser code should still depend on storage interfaces
  - database implementation details should stay inside the storage layer

## Apply Flow

- The intro page is treated specially:
  - resume selection/upload
  - cover letter generation/fill
  - verification before continuing
- Per-job orchestration is now explicit:
  - fetch details
  - classify skip vs quick apply
  - choose resume
  - gate by compatibility
  - enrich contact
  - apply
  - persist result
- Submit success is strict: Seek `/apply/success` is the success signal.
- Final review consent/privacy/terms checkboxes should be auto-ticked.
- `Show strong interest` should be ignored.

## Known Practical Limitations

- Common native questionnaire controls are handled first: text inputs, textareas, radios, checkboxes, and selects.
- Current custom-widget support covers common ARIA radiogroups and listboxes, but richer combobox/button-based widgets are not fully handled yet.
- Prefilled questionnaire answers are intentionally left in place for now unless the page requires intervention.
- External job links should be logged cleanly, but external flow itself is not part of the active runtime.

## Publish / Repo Hygiene

- Private/local runtime artifacts should stay out of git:
  - `seek_config_local.py`
  - logs
  - CSVs
  - debug prompt dumps
  - Q&A memory
- The README should explain the project clearly and honestly.
- The TODO should track both near-term fixes and deferred design work.

## Planned Next Directions

- Expand widget adapters for richer custom controls after more real runs.
- Refine the hybrid matcher, including weighting, thresholds, and better semantic memory reuse.
- Semantic normalization should preserve high-end ordering for resume selection:
  - a floor is useful to suppress random background cosine noise
  - a hard ceiling is not ideal for ranking multiple strong resumes against the same JD because it flattens meaningful differences
  - if the display score still wants a ceiling later, keep that separate from the ranking signal
- Use DB queries as the first eval/reporting layer instead of adding a separate eval CSV.
- The initial DB-backed eval/report layer is a small script over `jobs` and `qa_memory`, not a separate evaluation subsystem.
- Expand from per-job LangGraph orchestration to run-level orchestration only when it adds clear value:
  - explicit run states
  - checkpointed stop/resume
  - cleaner retry and human-checkpoint flows
- Provider routing and cost policy are worthwhile future architecture work once the current runtime behavior is stable.
- Human-in-the-loop state should eventually become persisted workflow state rather than only terminal interaction.
- Add better automated test coverage.
