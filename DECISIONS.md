# Decisions

This file records the current project decisions, constraints, and deferred ideas so they do not live only in chat history.

## Current Runtime Scope

- SeekBot currently supports **Seek Quick Apply only**.
- External apply flows and non-Quick Apply flows are out of scope for the active runtime.
- One configured LLM provider is used per run. There is no in-run provider fallback/orchestration layer.

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

- The default active local model is currently `gemma3`.
- The default hosted/template provider is currently Hugging Face using `deepseek-ai/DeepSeek-V3-0324`.
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
- Only answers with `confidence > 0.85` should be auto-accepted.
- Answers with `confidence <= 0.85` should prompt the user.
- Verified memory means a human accepted or provided the answer.
- Exact verified memory auto-reuses directly.
- Similar verified memory may auto-apply when its confidence is above the active threshold. Otherwise it should be presented to the user for confirmation.
- Native multi-select questions should use a dedicated multi-option LLM prompt and apply every supported option the model returns.
- Question extraction is a known weakness; DOM noise can still leak into the extracted question.
- The old static `question_answers` questionnaire dictionary is removed from the active questionnaire flow.
- Questionnaire memory may store unverified LLM answers as the latest state for that exact canonical question, but read paths must stay restricted to verified rows for direct reuse and trusted prompt context.
- String-based fuzzy memory reuse was intentionally removed as an auto-answer path. If non-exact memory reuse expands later, it should stay confirmation-gated and eventually use embeddings rather than lexical fuzzy matching.

## Storage

- Jobs and Q&A memory are moving behind a Postgres-backed storage layer.
- Jobs and Q&A memory are now primarily stored in Postgres, with CSV retained only as fallback/bootstrap.
- The primary storage path should stay behind the existing store-style boundary, not leak into Playwright/browser code.
- Existing CSV files are retained as fallback/bootstrap sources, not as the preferred runtime store.
- The Q&A memory store records the final answer actually applied or observed on the page, not every intermediate guess.
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
- Submit success is strict: Seek `/apply/success` is the success signal.
- Final review consent/privacy/terms checkboxes should be auto-ticked.
- `Show strong interest` should be ignored.

## Known Practical Limitations

- Common native questionnaire controls are handled first: text inputs, textareas, radios, checkboxes, and selects.
- Custom widgets and multi-select controls are not fully handled yet.
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

- Improve question extraction so the LLM sees the real employer question.
- Add support for custom widgets and multi-selects.
- Refine the hybrid matcher, including weighting, thresholds, and better semantic memory reuse.
- Move local persistence from CSV/files to Postgres with `pgvector`.
- Use DB queries as the first eval/reporting layer instead of adding a separate eval CSV.
- Add better automated test coverage.
