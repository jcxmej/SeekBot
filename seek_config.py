CONFIG = {
    "defaults": {
        "role_resumes": {
            "data engineer": "/absolute/path/to/data_engineer_resume.docx",
            "data scientist": "/absolute/path/to/data_scientist_resume.docx",
            "platform engineer": "/absolute/path/to/platform_engineer_resume.docx",
        },
        "location": "REPLACE_ME",
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
    },
    "storage": {
        "backend": "postgres",
        "dsn": "",
        "dsn_env": "SEEKBOT_POSTGRES_DSN",
        "fallback_to_csv": True,
        "bootstrap_from_csv": True,
    },
    "llm": {
        "enabled": True,
        "provider": "ollama",
        "model": "qwen3:8b",
        "api_key_env": "",
        "temperature": 0.1,
        "timeout_s": 45,
        "cover_letter_signature_name": "Your Name",
    },
}
