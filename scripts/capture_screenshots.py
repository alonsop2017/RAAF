"""
Capture screenshots of the RAAF web app for README documentation.
Generates a signed session cookie to bypass Google OAuth.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.sync_api import sync_playwright
from web.auth.session import session_manager

BASE_URL = "http://localhost:8000"
OUTPUT_DIR = project_root / "docs" / "screenshots"

# Use a real client/requisition from the system
CLIENT = "efrat_2026"
REQ = "REQ-2026-001-ECSM"

PAGES = [
    ("dashboard",     "/",                                          "Dashboard"),
    ("clients",       "/clients",                                   "Clients"),
    ("requisitions",  "/requisitions",                              "Requisitions"),
    ("requisition_detail", f"/requisitions/{CLIENT}/{REQ}",        "Requisition Detail"),
    ("candidates",    f"/candidates/{CLIENT}/{REQ}",                "Candidates"),
    ("assessments",   f"/assessments/{CLIENT}/{REQ}",               "Assessments"),
    ("reports",       f"/reports/{CLIENT}/{REQ}",                   "Reports"),
    ("pcr",           f"/pcr/{CLIENT}/{REQ}",                       "PCR Integration"),
    ("search",        "/search",                                    "Search"),
]


def make_session_cookie() -> dict:
    """Generate a valid signed session cookie for a fake admin user."""
    user_data = {
        "email": "alonso@peoplefindinc.com",
        "name": "Alonso P",
        "given_name": "Alonso",
        "family_name": "P",
        "picture": "",
        "email_verified": True,
    }
    token = session_manager.create_session(user_data)
    return {
        "name": session_manager.cookie_name,
        "value": token,
        "domain": "localhost",
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
    }


def capture():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cookie = make_session_cookie()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
        )
        context.add_cookies([cookie])
        page = context.new_page()

        for slug, path, label in PAGES:
            url = BASE_URL + path
            print(f"  Capturing {label}: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=15000)
                # Let any JS animations settle
                page.wait_for_timeout(500)
                out_path = OUTPUT_DIR / f"{slug}.png"
                page.screenshot(path=str(out_path), full_page=True)
                print(f"    Saved {out_path.name}")
            except Exception as e:
                print(f"    ERROR: {e}")

        browser.close()

    print(f"\nDone. Screenshots saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    capture()
