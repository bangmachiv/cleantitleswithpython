#!/usr/bin/env python3
import os
import re
import json
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================
TEMP_RUNTIME_FILE = "temp_runtime.json"
OUTPUT_FILE = "output.json"

REVIEW_IDENTIFIERS = [
    "hindimoviereview", "hindifilmreview", "moviereview", "filmreview", "review",
    "review and rating", "movie review and rating"
]

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
    "The Lensmen Reviews", "Suyash Pachauri Writes", "Film Information", "The Open Press"
]

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

        # FINAL FALLBACK: Just the Movie Name
        if movie_norm:
            candidates.append({"normalized": movie_norm})

    unique_candidates = []
    seen = set()
    for c in sorted(candidates, key=lambda x: len(x["normalized"]), reverse=True):
        if c["normalized"] not in seen:
            seen.add(c["normalized"])
            unique_candidates.append(c)

    return unique_candidates

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
# MAIN CLEANER EXECUTION
# ============================================================
def main():
    if not os.path.exists(TEMP_RUNTIME_FILE):
        print(f"[ERROR] {TEMP_RUNTIME_FILE} not found. Run finder.py first.")
        return

    with open(TEMP_RUNTIME_FILE, "r", encoding="utf-8") as f:
        runtime_data = json.load(f)

    timestamp = runtime_data.get("timestamp")
    movie_name = runtime_data.get("movie_name")
    entries = runtime_data.get("entries", [])

    print(f"[CLEANER] Processing {len(entries)} entries for movie: '{movie_name}'")

    candidates = build_candidates(movie_name)
    normalized_publishers = []
    for pub in PUBLISHERS:
        norm_pub, _ = normalize_with_positions(pub)
        normalized_publishers.append((norm_pub, len(norm_pub)))
    normalized_publishers.sort(key=lambda x: x[1], reverse=True)

    results = []

    for domain, raw_title in entries:
        cleaned_title = clean_title(raw_title, candidates, normalized_publishers) if raw_title else ""
        
        print(f"\nDomain: {domain}")
        print(f"Raw: {raw_title if raw_title else 'FAILED'}")
        print(f"Cleaned: {cleaned_title if cleaned_title else 'FAILED'}")

        results.append({
            "domain": domain,
            "cleaned_title": cleaned_title,
            "raw_title": raw_title
        })

    new_run_block = {
        "timestamp": timestamp,
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

    print(f"\n[CLEANER] Complete. Finalized results saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
