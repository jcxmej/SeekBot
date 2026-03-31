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
  2. LLM
  3. user if confidence is too low
- Only answers with `confidence > 0.8` should be auto-accepted.
- Answers with `confidence <= 0.8` should prompt the user.
- Verified memory means a human accepted or provided the answer.
- Exact verified memory is the only memory auto-reuse path in the active flow.
- Native multi-select questions should use a dedicated multi-option LLM prompt and apply every supported option the model returns.
- Question extraction is a known weakness; DOM noise can still leak into the extracted question.
- Standard answers are currently provided to the LLM as table context, but a safe direct standard-answer bypass should be reintroduced later.
- String-based fuzzy memory reuse was intentionally removed. If non-exact memory reuse is added later, it should use embeddings rather than lexical fuzzy matching.

## Q&A Memory CSV

- The Q&A memory CSV is a local growing answer store.
- It records the final answer actually applied or observed on the page, not every intermediate guess.
- Only user-confirmed answers are marked verified by default.
- Low-confidence edge cases currently need a cleaner separation between:
  - auto-accept threshold
  - memory-write policy

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
- Add better automated test coverage.
