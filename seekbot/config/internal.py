from seekbot.config.matching import GLOBAL_MATCHING_TAXONOMY


INTERNAL_CONFIG = {
    "defaults": {
        "location": "",
        "user_data_dir": "/tmp/seekbot-chrome",
        "profile_directory": "Default",
        "compatibility_threshold": 5.0,
        "resume_switch_margin": 2.0,
        "max_pages": 3,
        "max_applications": 0,
    },
    "logging": {
        "run_log_path": "seekbot_run.log",
        "llm_log_path": "seekbot_llm.log",
        "debug_click_log_path": "seekbot_clicks.log",
        "csv_log_path": "seekbot_jobs.csv",
        "question_memory_csv_path": "seekbot_qa_memory.csv",
    },
    "storage": {
        "backend": "postgres",
        "dsn": "",
        "dsn_env": "SEEKBOT_POSTGRES_DSN",
        "fallback_to_csv": True,
        "bootstrap_from_csv": True,
        "vector_dims": 384,
    },
    "llm": {
        "enabled": True,
        "provider": "ollama",
        "url": "http://localhost:11434/api/generate",
        "model": "qwen3:8b",
        "base_url": "",
        "api_key_env": "",
        "anthropic_max_tokens": 1024,
        "temperature": 0.1,
        "timeout_s": 45,
        "max_job_chars": 4000,
        "question_max_answer_chars": 400,
        "question_low_confidence_threshold": 0.85,
        "cover_letter_max_chars": 900,
        "cover_letter_signature_name": "Candidate",
        "contact_prompt": (
            "Extract HR or recruiter contact details from the JOB DESCRIPTION.\n"
            "Populate the ContactExtraction response fields: name, email, phone.\n"
            "If a field is not present, leave it empty.\n"
            "\nJOB DESCRIPTION:\n{job}\n"
        ),
        "cover_letter_prompt": (
            "Write a short, tailored cover letter for this job application.\n"
            "Use the RESUME and JOB DESCRIPTION only.\n"
            "Populate the CoverLetter response fields paragraph_one and paragraph_two only.\n"
            "Do not include greeting, closing, signature, markdown, bullet points, placeholders, or extra commentary.\n"
            "\nRESUME:\n{resume}\n\nJOB DESCRIPTION:\n{job}\n"
        ),
        "question_prompt": (
            "You answer application questions using RESUME and QA_MEMORY_TABLE.\n"
            "Use RESUME and QA_MEMORY_TABLE as the only evidence about the candidate.\n"
            "When QA_MEMORY_TABLE contains a directly relevant answer, treat it as the primary source of truth.\n"
            "Prefer QA_MEMORY_TABLE over weaker inference from the RESUME.\n"
            "Rows under VERIFIED_PRIOR_QUESTIONNAIRE_QA are previously confirmed employer-question answers with verified=true.\n"
            "If VERIFIED_PRIOR_QUESTIONNAIRE_QA contains the same underlying fact asked in different words, prefer that answer over fresh inference and map it carefully to the current question or options.\n"
            "If VERIFIED_PRIOR_QUESTIONNAIRE_QA establishes a stable personal fact about the candidate, keep that fact consistent across wording changes unless the current question is clearly asking something different.\n"
            "Do not infer a formal personal credential or eligibility status from employer requirements, current location, current employment, industry, or job-posting language.\n"
            "This includes security clearances, citizenship or permanent residency, visa or work-rights status, sponsorship needs, licences, police checks, salary expectations, pay rates, and similar personal credentials.\n"
            "For years-of-experience questions, estimate years from the RESUME timeline and responsibilities.\n"
            "Do not require an exact title match if the resume shows clearly equivalent or closely related work.\n"
            "Use overlapping duties, tools, and domain context to decide whether roles are substantially the same kind of experience.\n"
            "Do not infer notice period, immediate availability, or zero notice from employment dates like 'Present' or from job-posting language such as 'Quick apply'.\n"
            "Populate the QuestionAnswer response fields: answer, confidence, reason, question_issue.\n"
            "confidence must be a number between 0 and 1.\n"
            "confidence must reflect how certain you are that the answer is correct for this candidate, not just that you understood the question.\n"
            "If the answer is uncertain, approximate, or weakly supported, lower the confidence.\n"
            "Only use confidence above 0.85 when the answer is directly supported by the RESUME or by VERIFIED_PRIOR_QUESTIONNAIRE_QA.\n"
            "If you are mapping a stable personal fact or a sensitive personal credential without direct support from the RESUME or verified prior answers, keep confidence low so the user can confirm it.\n"
            "If RESUME and QA_MEMORY_TABLE do not support an answer, set answer to \"N/A\" and confidence to 0.0.\n"
            "question_issue must be an empty string when QUESTION is a clear, sensible employer question.\n"
            "If QUESTION looks synthetic, unclear, incomplete, or not like a real employer question, set question_issue to a short phrase.\n"
            "question_issue is for debugging only. Still answer the question best-effort from the available context whenever possible.\n"
            "reason must be a short phrase explaining uncertainty or evidence, not a full paragraph.\n"
            "If the answer came from QA_MEMORY_TABLE, say that briefly in reason.\n"
            "If OPTIONS are provided, answer must be copied exactly from OPTIONS.\n"
            "If multiple options apply, return a comma-separated string of exact option texts.\n"
            "\nRESUME:\n{resume}\n\n"
            "QA_MEMORY_TABLE:\n{qa_memory_table}\n\n"
            "QUESTION:\n{question}\n\n"
            "OPTIONS (if any):\n{options}\n"
        ),
        "option_question_prompt": (
            "You are answering an application question with a fixed option list.\n"
            "Use RESUME and QA_MEMORY_TABLE as context.\n"
            "Use RESUME and QA_MEMORY_TABLE as the only evidence about the candidate.\n"
            "When QA_MEMORY_TABLE contains a directly relevant answer, treat it as the primary source of truth.\n"
            "Prefer QA_MEMORY_TABLE over weaker inference from the RESUME.\n"
            "Rows under VERIFIED_PRIOR_QUESTIONNAIRE_QA are previously confirmed employer-question answers with verified=true.\n"
            "If VERIFIED_PRIOR_QUESTIONNAIRE_QA contains the same underlying fact asked in different words, prefer that answer over fresh inference and map it carefully to the current OPTIONS.\n"
            "If VERIFIED_PRIOR_QUESTIONNAIRE_QA establishes a stable personal fact about the candidate, keep that fact consistent across wording changes unless the current question is clearly asking something different.\n"
            "Do not infer a formal personal credential or eligibility status from employer requirements, current location, current employment, industry, or job-posting language.\n"
            "This includes security clearances, citizenship or permanent residency, visa or work-rights status, sponsorship needs, licences, police checks, salary expectations, pay rates, and similar personal credentials.\n"
            "For years-of-experience questions, estimate years from the RESUME timeline and responsibilities.\n"
            "Do not require an exact title match if the resume shows clearly equivalent or closely related work.\n"
            "Use overlapping duties, tools, and domain context to decide whether roles are substantially the same kind of experience.\n"
            "Do not infer notice period, immediate availability, or zero notice from employment dates like 'Present' or from job-posting language such as 'Quick apply'.\n"
            "Choose ONLY from the provided OPTIONS.\n"
            "Populate the QuestionAnswer response fields: answer, confidence, reason, question_issue.\n"
            "answer must be copied exactly from OPTIONS.\n"
            "If multiple options apply, answer must be a comma-separated string of exact option texts copied from OPTIONS.\n"
            "confidence must be a number between 0 and 1.\n"
            "confidence must reflect how certain you are that the chosen option is correct for this candidate, not just that it is the closest-looking option.\n"
            "If none is a perfect literal match, choose the closest option that best fits the candidate context and lower the confidence.\n"
            "Only use confidence above 0.85 when the chosen option is directly supported by the RESUME or by VERIFIED_PRIOR_QUESTIONNAIRE_QA.\n"
            "If you are mapping a stable personal fact or a sensitive personal credential without direct support from the RESUME or verified prior answers, keep confidence low so the user can confirm it.\n"
            "For ordered year options, choose the highest option that is still supported by the RESUME.\n"
            "Do not choose a positive experience or certification option unless RESUME or QA_MEMORY_TABLE supports it.\n"
            "question_issue must be an empty string when QUESTION is a clear, sensible employer question.\n"
            "If QUESTION looks synthetic, unclear, incomplete, or not like a real employer question, set question_issue to a short phrase.\n"
            "question_issue is for debugging only. Still choose the best option from OPTIONS whenever possible.\n"
            "reason must be a short phrase explaining uncertainty or evidence, not a full paragraph.\n"
            "If the answer came from QA_MEMORY_TABLE, say that briefly in reason.\n"
            "Do not invent new wording for answer.\n"
            "\nRESUME:\n{resume}\n\n"
            "QA_MEMORY_TABLE:\n{qa_memory_table}\n\n"
            "QUESTION:\n{question}\n\n"
            "OPTIONS:\n{options}\n"
        ),
        "multi_option_question_prompt": (
            "You are answering an application question where multiple options may be selected.\n"
            "Use RESUME and QA_MEMORY_TABLE as context.\n"
            "Use RESUME and QA_MEMORY_TABLE as the only evidence about the candidate.\n"
            "When QA_MEMORY_TABLE contains a directly relevant answer, treat it as the primary source of truth.\n"
            "Prefer QA_MEMORY_TABLE over weaker inference from the RESUME.\n"
            "Rows under VERIFIED_PRIOR_QUESTIONNAIRE_QA are previously confirmed employer-question answers with verified=true.\n"
            "If VERIFIED_PRIOR_QUESTIONNAIRE_QA contains the same underlying fact asked in different words, prefer that answer over fresh inference and map it carefully to the current OPTIONS.\n"
            "If VERIFIED_PRIOR_QUESTIONNAIRE_QA establishes a stable personal fact about the candidate, keep that fact consistent across wording changes unless the current question is clearly asking something different.\n"
            "Do not infer a formal personal credential or eligibility status from employer requirements, current location, current employment, industry, or job-posting language.\n"
            "This includes security clearances, citizenship or permanent residency, visa or work-rights status, sponsorship needs, licences, police checks, salary expectations, pay rates, and similar personal credentials.\n"
            "Do not infer notice period, immediate availability, or zero notice from employment dates like 'Present' or from job-posting language such as 'Quick apply'.\n"
            "Choose every option from OPTIONS that is supported by RESUME or QA_MEMORY_TABLE.\n"
            "Do not force the answer to a single option if multiple supported options apply.\n"
            "If a negative option such as 'No' conflicts with positive options, do not include the negative option.\n"
            "Populate the QuestionAnswer response fields: answer, confidence, reason, question_issue.\n"
            "answer must be a comma-separated string of exact option texts copied from OPTIONS.\n"
            "If exactly one option applies, return that one exact option text.\n"
            "If no positive option is supported but a negative option like 'No' exists, return the exact negative option text.\n"
            "confidence must be a number between 0 and 1.\n"
            "confidence must reflect how certain you are that the chosen options are correct for this candidate.\n"
            "Only use confidence above 0.85 when the chosen options are directly supported by the RESUME or by VERIFIED_PRIOR_QUESTIONNAIRE_QA.\n"
            "If you are mapping a stable personal fact or a sensitive personal credential without direct support from the RESUME or verified prior answers, keep confidence low so the user can confirm it.\n"
            "question_issue must be an empty string when QUESTION is a clear, sensible employer question.\n"
            "If QUESTION looks synthetic, unclear, incomplete, or not like a real employer question, set question_issue to a short phrase.\n"
            "question_issue is for debugging only. Still choose the best supported options from OPTIONS whenever possible.\n"
            "reason must be a short phrase explaining uncertainty or evidence, not a full paragraph.\n"
            "If the answer came from QA_MEMORY_TABLE, say that briefly in reason.\n"
            "Do not invent new wording for answer.\n"
            "\nRESUME:\n{resume}\n\n"
            "QA_MEMORY_TABLE:\n{qa_memory_table}\n\n"
            "QUESTION:\n{question}\n\n"
            "OPTIONS:\n{options}\n"
        ),
    },
    "matching": {
        "taxonomy": GLOBAL_MATCHING_TAXONOMY,
        "semantic_enabled": True,
        "embedding_model": "all-MiniLM-L6-v2",
        "semantic_weight": 0.55,
        "keyword_weight": 0.45,
        "semantic_floor_cosine": 0.15,
        "semantic_full_cosine": 0.65,
        "resume_selection": {
            "compatibility_weight": 0.75,
            "title_weight": 0.2,
            "search_role_weight": 0.05,
            "title_match_threshold": 0.6,
        },
    },
}
