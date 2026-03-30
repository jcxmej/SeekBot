from seekbot.config.matching import GLOBAL_MATCHING_TAXONOMY


INTERNAL_CONFIG = {
    "defaults": {
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
    "llm": {
        "enabled": True,
        "provider": "ollama_client",
        "url": "http://localhost:11434/api/generate",
        "model": "gemma3",
        "base_url": "",
        "api_key_env": "",
        "anthropic_max_tokens": 1024,
        "temperature": 0.1,
        "timeout_s": 45,
        "max_job_chars": 4000,
        "question_max_answer_chars": 400,
        "question_low_confidence_threshold": 0.8,
        "cover_letter_max_chars": 900,
        "cover_letter_signature_name": "Candidate",
        "contact_prompt": (
            "Extract HR or recruiter contact details from the JOB DESCRIPTION.\n"
            "Return ONLY a JSON object with keys: name, email, phone.\n"
            "If a field is not present, use an empty string.\n"
            "\nJOB DESCRIPTION:\n{job}\n"
        ),
        "cover_letter_prompt": (
            "Write a short, tailored cover letter for this job application.\n"
            "Use the RESUME and JOB DESCRIPTION only.\n"
            "Return ONLY plain text in exactly this format:\n"
            "Dear Hiring Manager,\n\n"
            "<two short tailored paragraphs>\n\n"
            "Kind regards,\n"
            "{signature_name}\n\n"
            "Do not add any preamble such as 'Here is...' or 'Tailored cover letter:'.\n"
            "Do not use markdown, bullet points, placeholders, or extra commentary.\n"
            "\nRESUME:\n{resume}\n\nJOB DESCRIPTION:\n{job}\n"
        ),
        "question_prompt": (
            "You answer application questions using RESUME, JOB DESCRIPTION, and QA_MEMORY_TABLE.\n"
            "Return ONLY a JSON object with keys: answer, confidence, reason, question_issue.\n"
            "confidence must be a number between 0 and 1.\n"
            "confidence must reflect how certain you are that the answer is correct for this candidate, not just that you understood the question.\n"
            "If the answer is uncertain, approximate, or weakly supported, lower the confidence.\n"
            "If the resume does not support an answer, set answer to \"N/A\" and confidence to 0.0.\n"
            "question_issue must be an empty string when QUESTION is a clear, sensible employer question.\n"
            "If QUESTION looks synthetic, unclear, incomplete, or not like a real employer question, set question_issue to a short phrase.\n"
            "question_issue is for debugging only. Still answer the question best-effort from the available context whenever possible.\n"
            "reason must be a short phrase explaining uncertainty or evidence, not a full paragraph.\n"
            "If OPTIONS are provided, answer must be copied exactly from OPTIONS.\n"
            "If multiple options apply, return a comma-separated string of exact option texts.\n"
            "Do not include any explanation, labels, or extra text outside the JSON object.\n"
            "\nRESUME:\n{resume}\n\nJOB DESCRIPTION:\n{job}\n\n"
            "QA_MEMORY_TABLE:\n{qa_memory_table}\n\n"
            "QUESTION:\n{question}\n\n"
            "OPTIONS (if any):\n{options}\n"
        ),
        "option_question_prompt": (
            "You are answering an application question with a fixed option list.\n"
            "Use RESUME, JOB DESCRIPTION, and QA_MEMORY_TABLE as context.\n"
            "Choose ONLY from the provided OPTIONS.\n"
            "Return ONLY a JSON object with keys: answer, confidence, reason, question_issue.\n"
            "answer must be copied exactly from OPTIONS.\n"
            "If multiple options apply, answer must be a comma-separated string of exact option texts copied from OPTIONS.\n"
            "confidence must be a number between 0 and 1.\n"
            "confidence must reflect how certain you are that the chosen option is correct for this candidate, not just that it is the closest-looking option.\n"
            "If none is a perfect literal match, choose the closest option that best fits the candidate context and lower the confidence.\n"
            "question_issue must be an empty string when QUESTION is a clear, sensible employer question.\n"
            "If QUESTION looks synthetic, unclear, incomplete, or not like a real employer question, set question_issue to a short phrase.\n"
            "question_issue is for debugging only. Still choose the best option from OPTIONS whenever possible.\n"
            "reason must be a short phrase explaining uncertainty or evidence, not a full paragraph.\n"
            "Do not explain your reasoning.\n"
            "Do not invent new wording.\n"
            "\nRESUME:\n{resume}\n\nJOB DESCRIPTION:\n{job}\n\n"
            "QA_MEMORY_TABLE:\n{qa_memory_table}\n\n"
            "QUESTION:\n{question}\n\n"
            "OPTIONS:\n{options}\n"
        ),
    },
    "matching": {
        "taxonomy": GLOBAL_MATCHING_TAXONOMY,
    },
}
