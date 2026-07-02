"""Capture live-app screenshots for the feature summary (docs/assets/screenshots/).

Drives the running app at http://localhost:8007 with Playwright. English for
the main feature shots; French for the overview and one chat exchange, to
show the multilingual UI. Run (server must already be up):

    python scripts/capture_screenshots.py
"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "assets" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:8007"

# Nav labels per language (from the frontend STR tables)
NAV_EN = {
    "overview": "Overview", "chat": "Assistant", "documents": "SitRep library",
    "dq_review": "Single review", "dq_compare": "Version compare",
    "topics": "Topics & gaps",
}
NAV_FR = {"overview": "Vue d ensemble", "chat": "Assistant"}


def shot(page, name):
    page.wait_for_timeout(1200)  # let charts/plotly settle
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)
    print(f"captured {name}.png")


def click_nav(page, label):
    page.get_by_text(label, exact=True).first.click()
    page.wait_for_timeout(800)


def set_lang(page, code):
    page.get_by_text(code, exact=True).first.click()
    page.wait_for_timeout(600)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 900},
                                device_scale_factor=1.5)
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(2500)

        # --- English shots (main features) -----------------------------------
        set_lang(page, "EN")
        shot(page, "overview_en")

        click_nav(page, NAV_EN["documents"])
        shot(page, "library_en")

        click_nav(page, NAV_EN["dq_review"])
        shot(page, "dq_review_en")

        click_nav(page, NAV_EN["dq_compare"])
        shot(page, "dq_compare_en")

        click_nav(page, NAV_EN["topics"])
        shot(page, "topics_en")

        # Chat with a real question (grounded, cited answer). Falls back to the
        # empty chat screen if the model call does not come back in time.
        click_nav(page, NAV_EN["chat"])
        page.wait_for_timeout(600)
        try:
            box = page.locator("textarea, input").last
            box.fill("How many confirmed cases and deaths in the latest report, "
                     "and what is the trend?")
            box.press("Enter")
            page.wait_for_timeout(1000)
            # wait for the typing indicator to be replaced (up to 90 s)
            for _ in range(90):
                if page.get_by_text("...", exact=True).count() == 0:
                    break
                time.sleep(1)
            page.wait_for_timeout(1500)
        except Exception as e:  # noqa: BLE001 - screenshot whatever is there
            print(f"chat interaction failed ({e}); capturing as-is")
        shot(page, "chat_en")

        # --- French shots (multilingual emphasis) -----------------------------
        set_lang(page, "FR")
        click_nav(page, NAV_FR["overview"])
        shot(page, "overview_fr")

        click_nav(page, NAV_FR["chat"])
        page.wait_for_timeout(600)
        try:
            box = page.locator("textarea, input").last
            box.fill("Quelle est la tendance de la letalite (CFR) sur les "
                     "derniers rapports ?")
            box.press("Enter")
            page.wait_for_timeout(1000)
            for _ in range(90):
                if page.get_by_text("...", exact=True).count() == 0:
                    break
                time.sleep(1)
            page.wait_for_timeout(1500)
        except Exception as e:  # noqa: BLE001
            print(f"fr chat interaction failed ({e}); capturing as-is")
        shot(page, "chat_fr")

        browser.close()
    print("done")


if __name__ == "__main__":
    main()
