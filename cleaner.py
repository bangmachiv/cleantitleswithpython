#!/usr/bin/env python3
import os
import re
import json
import urllib.parse
import html  # Decodes HTML entities BEFORE string processing
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
OUTPUT_FILE = "output.json"
MIN_VALID_HTML_BYTES = 2000

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

# Added the new "rating" identifiers
REVIEW_IDENTIFIERS = [
    "hindimoviereview", "hindifilmreview", "moviereview", "filmreview", "review",
    "review and rating", "movie review and rating"
]

# Added "Film Information" and "Telegraph India" to catch the remaining artifacts
PUBLISHERS = [
    "Bollywood Hungama", "BollySpice", "Cinema Express", "Film Companion", 
    "Glamsham", "High On Films", "Koimoi", "Movie Talkies", "PeepingMoon", 
    "DNA", "Firstpost", "Gadgets 360", "IANS Live", "Moneycontrol", 
    "Rediff.com", "Rediff.com movies", "Scroll.in", "South Asian Herald", 
    "The Federal", "The News Minute", "The Quint", "Business Standard", "Mint", 
    "Filmfare", "India Today", "Outlook", "Hindustan Times", "The Hindu", 
    "The Indian Express", "The Sunday Guardian", "The Telegraph", "Telegraph India",
    "The Times of India", "Deccan Chronicle", "Deccan Herald", 
    "Free Press Journal", "Mid-Day", "The Siasat Daily", "The Tribune", 
    "Amar Ujala", "Dainik Bhaskar", "Dainik Jagran", "Hindustan", 
    "Navbharat Times", "Lokmat", "NDTV", "News18", "WION", "Aaj Tak", "ABP",
    "The Lensmen Reviews", "Suyash Pachauri Writes", "Film Information"
]

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
# FALLBACK DOWNLOADERS
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

# ============================================================
# TITLE CLEANING ALGORITHM
# ============================================================
def normalize_with_positions(text):
    normalized = ""
    positions = []
    for original_index, char in enumerate(text):
        if char.isalnum():
            normalized += char.lower()
            positions.append(original_index)
    return normalized, positions

def get_movie_variants(movie_name):
    variants = []
    names = [n.strip() for n in movie_name.split(",") if n.strip()]
    
    for name in names:
        if name.lower() not in [v.lower() for v in variants]:
            variants.append(name)
        match = re.match(r'^(.+?)\s+[:\-]\s+(.+)$', name)
        if match:
            main_title = match.group(1).strip()
            if main_title and main_title.lower() not in [v.lower() for v in variants]:
                variants.append(main_title)
    return variants

def build_candidates(movie_name):
    variants = get_movie_variants(movie_name)
    candidates = []
    for variant in variants:
        movie_norm, _ = normalize_with_positions(variant)
        for identifier in REVIEW_IDENTIFIERS:
            ident_norm, _ = normalize_with_positions(identifier)
            candidates.append({"normalized": movie_norm + ident_norm})
            candidates.append({"normalized": ident_norm + movie_norm})
            
    candidates.sort(key=lambda x: len(x["normalized"]), reverse=True)
    return candidates

def clean_title(raw_title, candidates, normalized_publishers):
    if not raw_title or not raw_title.strip():
        return ""
        
    title_norm, positions = normalize_with_positions(raw_title)
    
    # STEP 1 & 2: Rightmost Movie/Review Match
    extracted_text = ""
    for candidate in candidates:
        match_idx = title_norm.rfind(candidate["normalized"])
        if match_idx != -1:
            match_end = match_idx + len(candidate["normalized"])
            
            if match_end >= len(positions):
                return ""
                
            original_start = positions[match_end]
            extracted_text = raw_title[original_start:]
            break
            
    if not extracted_text:
        return "" 
        
    # STEP 3: Rightmost Pipe (|) Removal
    r_pipe_idx = extracted_text.rfind('|')
    if r_pipe_idx != -1:
        extracted_text = extracted_text[:r_pipe_idx].strip()
        
    # STEP 4: Publisher Removal 
    ext_norm, ext_positions = normalize_with_positions(extracted_text)
    for pub_norm, _ in normalized_publishers:
        if ext_norm.endswith(pub_norm):
            match_start_norm_idx = len(ext_norm) - len(pub_norm)
            if match_start_norm_idx == 0:
                extracted_text = ""
            else:
                original_cut_idx = ext_positions[match_start_norm_idx]
                extracted_text = extracted_text[:original_cut_idx]
            break

    # STEP 5: Trailing Cleanup
    extracted_text = re.sub(r'[\s\-–—|]+$', '', extracted_text)
    return extracted_text

# ============================================================
# MAIN PIPELINE EXECUTION
# ============================================================
def main():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] {INPUT_FILE} not found in root directory.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] input.txt is empty.")
        return

    movie_name = lines[0]
    urls = lines[1:]

    print(f"[INFO] Initializing. Movie: '{movie_name}' | URLs: {len(urls)}")

    candidates = build_candidates(movie_name)
    normalized_publishers = []
    for pub in PUBLISHERS:
        norm_pub, _ = normalize_with_positions(pub)
        normalized_publishers.append((norm_pub, len(norm_pub)))
    normalized_publishers.sort(key=lambda x: x[1], reverse=True)

    results = []

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
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
            
            print(f"\n--- [{index}/{len(urls)}] {domain} ---")
            print(f"URL: {url}")

            html_content = None
            raw_title = ""
            used_tier = None

            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # CHANGED: 8000ms wait instead of 5000ms. 
                # This perfectly mirrors 03_download.py to bypass Indian Express anti-bot delays.
                page.wait_for_timeout(8000) 
                
                temp_content = page.content()
                page.close()

                if is_valid_html(temp_content):
                    html_content = temp_content
                    used_tier = "Tier 1 (Playwright Stealth)"
            except Exception:
                pass

            if not html_content:
                html_content, used_tier = fallback_download(url)

            if not html_content:
                html_content, used_tier = scrape_do_fallback(url)

            if html_content:
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    raw_title = html.unescape(raw_title)
                    
            cleaned_title = clean_title(raw_title, candidates, normalized_publishers) if raw_title else ""

            print(f"Downloaded: {'Y (' + used_tier + ')' if html_content else 'N'}")
            print(f"Title found: {raw_title if raw_title else 'FAILED'}")
            print(f"Cleaned: {cleaned_title if cleaned_title else 'FAILED'}")

            results.append({
                "domain": domain,
                "cleaned_title": cleaned_title,
                "raw_title": raw_title
            })

        browser.close()

    new_run_block = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "movie_name": movie_name,
        "results": results
    }

    existing_data = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    existing_data = []
        except json.JSONDecodeError:
            pass

    existing_data.insert(0, new_run_block)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=4)

    print(f"\n[INFO] Run complete. JSON updated with latest block at the top.")

if __name__ == "__main__":
    main()
