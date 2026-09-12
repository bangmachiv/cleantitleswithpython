#!/usr/bin/env python3
import os
import re
import json
import urllib.parse
import html
from datetime import datetime

# -----------------------------------------------------------------------------
# DOWNLOADER DEPENDENCIES
# -----------------------------------------------------------------------------
from curl_cffi import requests as cffi_requests
import requests as standard_requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# ============================================================
# CONFIGURATION
# ============================================================
SCRAPE_DO_TOKEN = os.environ.get("SCRAPE_DO_TOKEN")

INPUT_FILE = "input.txt"
TEMP_RUNTIME_FILE = "temp_runtime.json"
LOG_FILE = "logs.txt"
MIN_VALID_HTML_BYTES = 2000

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

# ============================================================
# HELPER: LOGGING
# ============================================================
def log_msg(msg):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# ============================================================
# HELPER: DOWNLOAD VALIDATION
# ============================================================
def is_valid_html(html_content: str) -> bool:
    if not html_content or len(html_content) < MIN_VALID_HTML_BYTES:
        return False
    if len(html_content) > 80000:
        return True

    lower_html = html_content.lower()
    bad_titles = ["<title>just a moment...</title>", "<title>attention required!</title>", "<title>security challenge</title>"]
    for title in bad_titles:
        if title in lower_html:
            return False

    bad_signatures = ["enable javascript and cookies to continue", "please verify you are a human", "challenge-platform"]
    for sig in bad_signatures:
        if sig in lower_html:
            return False

    return True

# ============================================================
# FALLBACK DOWNLOADERS (TIERS 2 to 6)
# ============================================================
def fallback_download(url: str):
    try:
        session = cffi_requests.Session(impersonate="chrome120")
        session.headers.update(HTTP_HEADERS)
        response = session.get(url, timeout=20)
        if response.status_code == 200 and is_valid_html(response.text):
            return response.text, "Tier 2 (curl_cffi)"
    except Exception:
        pass
    return None, None

def scrape_do_fallback(url: str):
    if not SCRAPE_DO_TOKEN:
        return None, None
    encoded_url = urllib.parse.quote(url)
    api_url = f"http://api.scrape.do/?token={SCRAPE_DO_TOKEN}&url={encoded_url}&render=true&super=true&geoCode=in"
    try:
        response = standard_requests.get(api_url, timeout=60)
        if response.status_code == 200 and is_valid_html(response.text):
            return response.text, "Tier 3 (Scrape.do)"
    except Exception:
        pass
    return None, None

def amp_cache_fallback(url: str):
    try:
        parsed = urllib.parse.urlparse(url)
        amp_host = parsed.netloc.replace('www.', '').replace('.', '-')
        s_part = "s/" if parsed.scheme == "https" else ""
        url_without_scheme = url.split("://")[-1]
        amp_url = f"https://{amp_host}.cdn.ampproject.org/c/{s_part}{url_without_scheme}"

        session = cffi_requests.Session(impersonate="chrome120")
        session.headers.update(HTTP_HEADERS)
        response = session.get(amp_url, timeout=20)

        if response.status_code == 200 and is_valid_html(response.text):
            return response.text, "Tier 4 (Google AMP Cache)"
    except Exception:
        pass
    return None, None

def google_translate_fallback(url: str):
    try:
        encoded_url = urllib.parse.quote(url)
        translate_url = f"https://translate.google.com/translate?sl=en&tl=en&u={encoded_url}"

        session = cffi_requests.Session(impersonate="chrome120")
        session.headers.update(HTTP_HEADERS)
        response = session.get(translate_url, timeout=20)

        if response.status_code == 200 and is_valid_html(response.text):
            return response.text, "Tier 5 (Google Translate)"
    except Exception:
        pass
    return None, None

def archive_fallback(url: str):
    try:
        archive_url = f"https://web.archive.org/web/2/{url}"

        session = cffi_requests.Session(impersonate="chrome120")
        session.headers.update(HTTP_HEADERS)
        response = session.get(archive_url, timeout=30)

        if response.status_code == 200 and is_valid_html(response.text):
            return response.text, "Tier 6 (Archive.org)"
    except Exception:
        pass
    return None, None

# ============================================================
# MAIN FINDER EXECUTION
# ============================================================
def main():
    # Initialize / Clear the log file for the new run
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"--- RUN STARTED: {datetime.now().astimezone().isoformat()} ---\n")

    if not os.path.exists(INPUT_FILE):
        log_msg(f"[ERROR] {INPUT_FILE} not found in root directory.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        log_msg("[ERROR] input.txt is empty.")
        return

    movie_name = lines[0]
    urls = lines[1:]

    log_msg(f"[FINDER] Initializing. Movie: '{movie_name}' | URLs: {len(urls)}")

    runtime_entries = []

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            channel="chrome", 
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent=HTTP_HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Referer": "https://www.google.com/"},
            locale="en-IN",
            timezone_id="Asia/Kolkata"
        )

        for index, url in enumerate(urls, start=1):
            domain = urllib.parse.urlparse(url).netloc
            domain = domain.replace("www.", "") if domain.startswith("www.") else domain
            
            log_msg(f"\n--- [{index}/{len(urls)}] {domain} ---")
            log_msg(f"URL: {url}")

            html_content = None
            raw_title = ""
            used_tier = None

            # TIER 1: Playwright
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(8000) 

                temp_content = page.content()
                page.close()

                if is_valid_html(temp_content):
                    html_content = temp_content
                    used_tier = "Tier 1 (Playwright Stealth)"
            except Exception:
                pass

            # CASCADING FALLBACKS (Tiers 2-6)
            if not html_content:
                html_content, used_tier = fallback_download(url)
            if not html_content:
                html_content, used_tier = scrape_do_fallback(url)
            if not html_content:
                html_content, used_tier = amp_cache_fallback(url)
            if not html_content:
                html_content, used_tier = google_translate_fallback(url)
            if not html_content:
                html_content, used_tier = archive_fallback(url)

            if html_content:
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    raw_title = html.unescape(raw_title)

            log_msg(f"Downloaded: {'Y (' + used_tier + ')' if html_content else 'N'}")
            log_msg(f"Title found: {raw_title if raw_title else 'FAILED'}")

            runtime_entries.append([domain, raw_title])

        browser.close()

    runtime_data = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "movie_name": movie_name,
        "entries": runtime_entries
    }

    with open(TEMP_RUNTIME_FILE, "w", encoding="utf-8") as f:
        json.dump(runtime_data, f, ensure_ascii=False, indent=4)

    log_msg(f"\n[FINDER] Complete. Saved runtime data to {TEMP_RUNTIME_FILE}")

if __name__ == "__main__":
    main()
