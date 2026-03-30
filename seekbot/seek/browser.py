import logging
import re

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from seekbot.settings import Settings

SEEK_BASE_URL = "https://www.seek.com.au"


class SeekBrowser:
    def __init__(
        self,
        settings: Settings,
        *,
        headless: bool = False,
        user_data_dir: str | None = None,
        profile_directory: str | None = None,
    ):
        self.settings = settings
        self.headless = headless
        self.user_data_dir = user_data_dir or settings.defaults.user_data_dir
        self.profile_directory = profile_directory or settings.defaults.profile_directory
        self._playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def start(self) -> "SeekBrowser":
        self._playwright = sync_playwright().start()
        self.context = self._playwright.chromium.launch_persistent_context(
            self.user_data_dir,
            channel="chrome",
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
            no_viewport=True,
        )
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()
        return self

    def close(self) -> None:
        if self.context is not None:
            self.context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def sign_in_if_needed(self, email: str | None, password: str | None, pause_for_login: bool = True) -> None:
        assert self.page is not None
        self.page.goto(SEEK_BASE_URL, wait_until="domcontentloaded")
        if not email or not password:
            logging.info("No credentials provided.")
            if self.headless:
                logging.warning("Headless mode without credentials cannot sign in; applications may fail.")
                return
            if pause_for_login:
                try:
                    input("Sign in to Seek in the opened browser, then press Enter to continue...")
                except EOFError:
                    logging.warning("No TTY available to pause for login; continuing.")
            return
        sign_in_link = self.page.get_by_role("link", name=re.compile("sign in", re.I))
        if sign_in_link.count():
            sign_in_link.first.click()
        email_input = self.page.get_by_label(re.compile("email", re.I))
        password_input = self.page.get_by_label(re.compile("password", re.I))
        if email_input.count() and password_input.count():
            email_input.first.fill(email)
            password_input.first.fill(password)
            submit = self.page.get_by_role("button", name=re.compile("sign in|log in", re.I))
            if submit.count():
                submit.first.click()
                self.page.wait_for_load_state("domcontentloaded")

