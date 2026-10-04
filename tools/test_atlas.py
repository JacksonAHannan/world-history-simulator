"""Run against an already running atlas: python tools/test_atlas.py --url URL.

Requires Playwright and Chromium. Generates a test world in the selected atlas.
Use an empty temporary --runs-dir when launching the server for this check.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import time

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", default="artifacts/browser")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.chromium)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="Generate world", exact=True).first.click()
        page.locator("#seed").fill("78321")
        page.locator("#provinces").select_option("240")
        page.locator("#generate-submit").click()
        expect(page.locator("#date")).to_have_text("9,000 BCE", timeout=30000)
        page.locator("#run").click()
        expect(page.locator("#run-label")).to_have_text("Pause")
        expect(page.locator("#run-label")).to_have_text("Run", timeout=180000)
        expect(page.locator("#date")).to_have_text("8,900 BCE", timeout=30000)
        page.locator(".province-list button").first.click()
        expect(page.locator("#branch-here")).to_be_visible()
        page.locator('[data-layer="political"]').click()
        page.screenshot(path=str(output/"atlas-desktop.png"), full_page=True)
        page.locator("#show-accounting").click()
        expect(page.locator("#event-content")).to_contain_text("Population identity")
        page.locator("#event-dialog .close-dialog").click()
        page.locator("#history-tab").click()
        page.locator("[data-event]").first.click()
        expect(page.locator("#event-content")).to_contain_text("Recorded changes")
        page.locator("#event-dialog .close-dialog").click()
        page.locator("#inspect-tab").click()
        page.locator("#branch-here").click()
        page.locator('#branch-form button[type="submit"]').click()
        expect(page.locator("#world-meta")).to_contain_text("intervention branch", timeout=30000)
        page.locator("#compare-tab").click()
        expect(page.locator("#comparison-result")).to_contain_text("0 people", timeout=30000)
        with page.expect_download(timeout=120000) as download_info:
            page.locator("#export").click()
        download_info.value.save_as(str(output/"world-history.zip"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output/"atlas-mobile.png"), full_page=True)
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow, "Mobile page overflows horizontally"
        assert not errors, errors
        browser.close()
    print("Atlas flows passed: generation, run, inspection, layers, provenance, branching, comparison, export and mobile layout.")


if __name__ == "__main__":
    main()
