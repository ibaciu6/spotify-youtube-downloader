#!/usr/bin/env python3
"""
Open Spotify in a browser for login and session persistence.
Reads credentials from .user/.password first (fallback: config.py),
saves storage state + cookies periodically, and keeps the browser open.
"""
import os
import re
import time
from playwright.sync_api import sync_playwright

from config import (
    COOKIES_FILE,
    WORK_DIR,
    SPOTIFY_EMAIL,
    SPOTIFY_PASSWORD,
    SPOTIFY_PROFILE_DIR,
    SPOTIFY_STORAGE_STATE,
)


def _read_secret_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def resolve_credentials():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_user = _read_secret_file(os.path.join(base_dir, ".user"))
    file_password = _read_secret_file(os.path.join(base_dir, ".password"))
    email = file_user or SPOTIFY_EMAIL
    password = file_password or SPOTIFY_PASSWORD
    return email, password


def save_cookies(context):
    cookies = context.cookies()
    os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for cookie in cookies:
            domain = cookie.get("domain", "")
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            secure = "TRUE" if cookie.get("secure") else "FALSE"
            expires = cookie.get("expires")
            expiry = str(int(expires)) if expires and expires > 0 else "0"
            f.write(
                f"{domain}\t{include_subdomains}\t{cookie.get('path', '/')}\t"
                f"{secure}\t{expiry}\t{cookie.get('name', '')}\t{cookie.get('value', '')}\n"
            )


def save_session(context):
    os.makedirs(WORK_DIR, exist_ok=True)
    context.storage_state(path=SPOTIFY_STORAGE_STATE)
    save_cookies(context)


def is_logged_in(page):
    try:
        page.goto("https://open.spotify.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if "accounts.spotify.com" in page.url:
            return False
        return True
    except Exception:
        return False


def _fill_first_visible(page, selector, value, timeout=12000):
    field = page.locator(selector).first
    field.wait_for(state="visible", timeout=timeout)
    field.fill(value)


def try_auto_login(page, email, password):
    page.goto("https://accounts.spotify.com/en/login", wait_until="domcontentloaded")
    username_selector = (
        'input[type="email"], input[name="username"], input[id="login-username"], '
        'input[autocomplete="username"], input[placeholder*="mail" i], '
        'input[placeholder*="user" i]'
    )
    _fill_first_visible(page, username_selector, email)

    # Spotify sometimes uses a two-step form (Continue), sometimes direct password.
    continue_button = page.get_by_role("button", name=re.compile(r"continue|next", re.I)).first
    try:
        if continue_button.is_visible(timeout=2000):
            continue_button.click(timeout=2000)
    except Exception:
        pass

    password_selector = 'input[type="password"], input[name="password"], input[id="login-password"]'
    _fill_first_visible(page, password_selector, password, timeout=20000)

    login_button = page.get_by_role("button", name=re.compile(r"log\s*in|sign\s*in", re.I)).first
    try:
        login_button.click(timeout=4000)
    except Exception:
        page.keyboard.press("Enter")

    page.wait_for_timeout(3500)


def main():
    email, password = resolve_credentials()

    print("=" * 50)
    print("Spotify – open browser for login")
    print("=" * 50)
    print()
    print("Browser will open with saved Spotify session when available.")
    print("Credentials source priority: .user/.password, then config.py.")
    print("Session + cookies will be saved automatically.")
    print()

    with sync_playwright() as p:
        os.makedirs(SPOTIFY_PROFILE_DIR, exist_ok=True)
        context = p.chromium.launch_persistent_context(
            user_data_dir=SPOTIFY_PROFILE_DIR,
            headless=False,
            args=["--remote-debugging-port=9222"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        if not is_logged_in(page):
            if email and password:
                try:
                    try_auto_login(page, email, password)
                    print("Auto-login submitted. Complete any captcha/2FA if prompted.")
                except Exception as e:
                    print(f"Auto-login failed: {e}")
                    print("Please log in manually in the browser window.")
            else:
                page.goto("https://accounts.spotify.com/en/login", wait_until="domcontentloaded")
                print("No credentials found in .user/.password or config.py.")
                print("Please log in manually in the browser window.")
        else:
            print("Existing Spotify session detected.")

        print()
        print("Keeping browser open. Press Ctrl+C here when done.")
        last_save = 0.0
        try:
            while True:
                now = time.time()
                if now - last_save >= 15:
                    save_session(context)
                    last_save = now
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nSaving session and closing browser...")
            try:
                save_session(context)
            except Exception:
                pass
        finally:
            try:
                context.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
