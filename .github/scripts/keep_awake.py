"""Open the Streamlit Community Cloud app in a headless browser so it doesn't go to sleep.

If the app is already asleep, click the "Yes, get this app back up!" button and
wait for it to finish starting. Exits non-zero only if the app can't be reached
or woken, so a failed run shows up in GitHub Actions.
"""

import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

APP_URL = os.environ.get(
    "APP_URL",
    "https://cathykam2006-gaf-peak-chart-builder-gaf-peak-app-iaai4v.streamlit.app/",
)
WAKE_BUTTON = "button:has-text('get this app back up')"
APP_FRAME = "iframe[title='streamlitApp']"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=90_000)

        # Give the page time to show either the app or the sleep screen.
        try:
            page.wait_for_selector(f"{WAKE_BUTTON}, {APP_FRAME}", timeout=60_000)
        except PlaywrightTimeout:
            print("Neither the app nor the sleep screen appeared.")
            page.screenshot(path="keep_awake.png", full_page=True)
            browser.close()
            return 1

        if page.locator(WAKE_BUTTON).count() > 0:
            print("App was asleep; clicking the wake-up button.")
            page.locator(WAKE_BUTTON).first.click()
            try:
                page.wait_for_selector(APP_FRAME, timeout=300_000)
            except PlaywrightTimeout:
                print("App did not finish starting within 5 minutes.")
                page.screenshot(path="keep_awake.png", full_page=True)
                browser.close()
                return 1
            print("App is awake again.")
        else:
            print("App is awake.")

        # Stay on the app briefly so the visit registers as real traffic.
        page.wait_for_timeout(20_000)
        page.screenshot(path="keep_awake.png", full_page=True)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
