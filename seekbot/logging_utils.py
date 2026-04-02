import logging
from dataclasses import dataclass

from seekbot.settings import LoggingConfig


@dataclass(frozen=True)
class BotLoggers:
    run: logging.Logger
    llm: logging.Logger
    action: logging.Logger


def _setup_file_logger(name: str, path: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = logging.FileHandler(path)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def configure_logging(logging_config: LoggingConfig) -> BotLoggers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)
    return BotLoggers(
        run=_setup_file_logger("seekbot.run", logging_config.run_log_path),
        llm=_setup_file_logger("seekbot.llm", logging_config.llm_log_path),
        action=_setup_file_logger("seekbot.action", logging_config.action_log_path),
    )
