import argparse

from seekbot.logging_utils import configure_logging
from seekbot.settings import load_settings
from seekbot.workflow import run_bot


def build_parser() -> argparse.ArgumentParser:
    settings = load_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--search-url", help="Optional full Seek search URL")
    parser.add_argument("--keywords", nargs="*", default=None, help="Search keywords override")
    parser.add_argument("--resume", default=None, help="Single resume override to use for all jobs")
    parser.add_argument("--email", help="Seek login email")
    parser.add_argument("--password", help="Seek login password")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--user-data-dir", default=settings.defaults.user_data_dir)
    parser.add_argument("--profile-directory", default=settings.defaults.profile_directory)
    parser.add_argument("--no-login-pause", action="store_true")
    parser.add_argument("--max", type=int, default=settings.defaults.max_applications)
    parser.add_argument("--max-pages", type=int, default=settings.defaults.max_pages)
    parser.add_argument(
        "--compatibility-threshold",
        "--threshold",
        dest="compatibility_threshold",
        type=float,
        default=settings.defaults.compatibility_threshold,
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    settings = load_settings()
    parser = build_parser()
    args = parser.parse_args()
    loggers = configure_logging(settings.logging)
    run_bot(args, settings, loggers)
