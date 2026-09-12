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
LOG_FILE = "logs.txt"

REVIEW_IDENTIFIERS = [
    "hindimoviereview", "hindifilmreview", "moviereview", "filmreview", "review",
    "review and rating", "movie review and rating",
    "review and rating (non-spoiler)", "movie review and rating (non-spoiler)"
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
    "The Lensmen Reviews", "Suyash Pachauri Writes", "Film Information", "The Open Press",
    "news", "reviews", "THR India"
]

def log_msg(msg):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

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
    primary = []
    secondary = []
    
    for variant in variants:
        movie_norm, _ = normalize_with_positions(variant)
        for identifier in REVIEW_IDENTIFIERS:
            ident_norm, _ = normalize_with_positions(identifier)
            primary.append({"normalized": movie_norm + ident_norm})
            primary.append({"normalized": ident_norm + movie_norm})
        if movie_norm:
            secondary.append({"normalized": movie_norm})

    def unique_sort(cand_list):
        uniq = []
        seen = set()
        for c in sorted(cand_list, key=lambda x: len(x["normalized"]), reverse=True):
            if c["normalized"] not in seen:
                seen.add(c["normalized"])
                uniq.append(c)
        return uniq

    return unique_sort(primary), unique_sort(secondary)

def clean_title(raw_title, primary_candidates, secondary_candidates, normalized_publishers):
    if not raw_title or not raw_title.strip():
        return ""

    title_norm, positions = normalize_with_positions(raw_title)

    has_primary = any(title_norm.find(c["normalized"]) != -1 for c in primary_candidates)
    active_candidates = primary_candidates if has_primary else secondary_candidates

    extracted_text = ""
    intervals = []
    i = 0
    
    while i < len(title_norm):
        best_match_len = 0
        for candidate in active_candidates:
            cand_norm = candidate["normalized"]
            if title_norm.startswith(cand_norm, i):
                if len(cand_norm) > best_match_len:
                    best_match_len = len(cand_norm)
        
        if best_match_len > 0:
            intervals.append((i, i + best_match_len))
            i += best_match_len
        else:
            i += 1
            
    if intervals:
        pieces = []
        for k in range(len(intervals)):
            start_norm = intervals[k][1]
            end_norm = intervals[k+1][0] if k + 1 < len(intervals) else len(title_norm)
            
            if start_norm >= len(positions):
                pieces.append("")
                continue
                
            raw_start = positions[start_norm]
            raw_end = positions[end_norm] if end_norm < len(positions) else len(raw_title)
            
            pieces.append(raw_title[raw_start:raw_end])
            
        best_piece = ""
        for piece in pieces:
            if len(piece.strip()) >= len(best_piece.strip()):
                best_piece = piece
                
        extracted_text = best_piece

    if not extracted_text:
        return "" 

    # STEP 3: Leftmost Pipe (|) Removal
    l_pipe_idx = extracted_text.find('|')
    if l_pipe_idx != -1:
        extracted_text = extracted_text[:l_pipe_idx].strip()

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
    extracted_text = re.sub(r'\s+[\-–—]\s+(?:[A-Z][a-zA-Z]*\s*){1,4}$', '', extracted_text)
    extracted_text = re.sub(r'[\s\-–—|]+$', '', extracted_text)
    
    for i, char in enumerate(extracted_text):
        if char.isalpha():
            extracted_text = extracted_text[:i] + char.upper() + extracted_text[i+1:]
            break

    return extracted_text

def main():
    if not os.path.exists(TEMP_RUNTIME_FILE):
        log_msg(f"[ERROR] {TEMP_RUNTIME_FILE} not found. Run finder.py first.")
        return

    with open(TEMP_RUNTIME_FILE, "r", encoding="utf-8") as f:
        runtime_data = json.load(f)

    timestamp = runtime_data.get("timestamp")
    movie_name = runtime_data.get("movie_name")
    entries = runtime_data.get("entries", [])

    log_msg(f"\n[CLEANER] Processing {len(entries)} entries for movie: '{movie_name}'")

    primary_cands, secondary_cands = build_candidates(movie_name)
    
    normalized_publishers = []
    for pub in PUBLISHERS:
        norm_pub, _ = normalize_with_positions(pub)
        normalized_publishers.append((norm_pub, len(norm_pub)))
    normalized_publishers.sort(key=lambda x: x[1], reverse=True)

    results = []
    downloaded_count = 0
    cleaned_count = 0

    for domain, raw_title in entries:
        cleaned_title = clean_title(raw_title, primary_cands, secondary_cands, normalized_publishers) if raw_title else ""

        is_downloaded = bool(raw_title)
        is_cleaned = bool(cleaned_title)
        
        if is_downloaded: downloaded_count += 1
        if is_cleaned: cleaned_count += 1

        log_msg(f"\nDomain: {domain}")
        log_msg(f"Raw: {raw_title if raw_title else 'FAILED'}")
        log_msg(f"Cleaned: {cleaned_title if cleaned_title else 'FAILED'}")

        results.append({
            "domain": domain,
            "cleaned_title": cleaned_title,
            "raw_title": raw_title,
            "is_downloaded": is_downloaded,
            "is_cleaned": is_cleaned
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

    log_msg("\n============================================================")
    log_msg("RUN STATISTICS")
    log_msg("============================================================")
    for res in results:
        down_status = "Y" if res['is_downloaded'] else "N"
        clean_status = "Y" if res['is_cleaned'] else "N"
        log_msg(f"Domain: {res['domain']} | Downloaded: {down_status} | Cleaned: {clean_status}")
    
    log_msg("------------------------------------------------------------")
    log_msg(f"Total URLs Processed    : {len(entries)}")
    log_msg(f"Successfully Downloaded : {downloaded_count}")
    log_msg(f"Successfully Cleaned    : {cleaned_count}")
    log_msg("============================================================")

    log_msg(f"\n[CLEANER] Complete. Finalized results saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
