from dataclasses import dataclass
from importlib import import_module

from seekbot.config import INTERNAL_CONFIG


@dataclass(frozen=True)
class Defaults:
    role_resumes: dict[str, str]
    location: str
    user_data_dir: str
    profile_directory: str
    compatibility_threshold: float
    resume_switch_margin: float
    max_pages: int
    max_applications: int


@dataclass(frozen=True)
class LoggingConfig:
    run_log_path: str
    llm_log_path: str
    action_log_path: str
    csv_log_path: str
    question_memory_csv_path: str


@dataclass(frozen=True)
class StorageConfig:
    backend: str
    dsn: str
    dsn_env: str
    fallback_to_csv: bool
    bootstrap_from_csv: bool
    vector_dims: int


@dataclass(frozen=True)
class Settings:
    defaults: Defaults
    logging: LoggingConfig
    storage: StorageConfig
    llm: dict
    raw: dict


def _load_config_module():
    for candidate in ("seek_config_local", "seek_config"):
        try:
            return import_module(candidate)
        except ModuleNotFoundError as exc:
            if exc.name != candidate:
                raise
            continue
    raise RuntimeError(
        "No config module found. Create seek_config_local.py for local settings or edit seek_config.py."
    )


def load_settings() -> Settings:
    module = _load_config_module()
    config = _merge_dicts(INTERNAL_CONFIG, getattr(module, "CONFIG"))

    defaults = config.get("defaults", {})
    logging_cfg = config.get("logging", {})
    storage_cfg = config.get("storage", {})
    return Settings(
        defaults=Defaults(
            role_resumes=dict(defaults.get("role_resumes", {})),
            location=str(defaults.get("location", "") or "").strip(),
            user_data_dir=defaults.get("user_data_dir", "/tmp/seekbot-chrome"),
            profile_directory=defaults.get("profile_directory", "Default"),
            compatibility_threshold=float(defaults.get("compatibility_threshold", 5.0)),
            resume_switch_margin=float(defaults.get("resume_switch_margin", 2.0)),
            max_pages=int(defaults.get("max_pages", 3)),
            max_applications=int(defaults.get("max_applications", 0)),
        ),
        logging=LoggingConfig(
            run_log_path=logging_cfg.get("run_log_path", "seekbot_run.log"),
            llm_log_path=logging_cfg.get("llm_log_path", "seekbot_llm.log"),
            action_log_path=logging_cfg.get("debug_click_log_path", "seekbot_actions.log"),
            csv_log_path=logging_cfg.get("csv_log_path", "seekbot_jobs.csv"),
            question_memory_csv_path=logging_cfg.get("question_memory_csv_path", "seekbot_qa_memory.csv"),
        ),
        storage=StorageConfig(
            backend=str(storage_cfg.get("backend", "postgres") or "postgres").strip().lower(),
            dsn=str(storage_cfg.get("dsn", "") or "").strip(),
            dsn_env=str(storage_cfg.get("dsn_env", "SEEKBOT_POSTGRES_DSN") or "SEEKBOT_POSTGRES_DSN").strip(),
            fallback_to_csv=bool(storage_cfg.get("fallback_to_csv", True)),
            bootstrap_from_csv=bool(storage_cfg.get("bootstrap_from_csv", True)),
            vector_dims=int(storage_cfg.get("vector_dims", 384)),
        ),
        llm=dict(config.get("llm", {})),
        raw=config,
    )


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
