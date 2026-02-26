#!/usr/bin/env python
# coding: utf-8

# =====================================================
# UTF-8 SAFE OUTPUT (CRITICAL FOR WINDOWS EXE)
# =====================================================

import sys
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# =====================================================
# IMPORTS
# =====================================================

import pandas as pd
from openai import OpenAI
from datetime import datetime
import json
import os
import gspread
import logging
import configparser
from pathlib import Path
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# =====================================================
# LOAD .env
# =====================================================

def load_env():
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent

    env_path = base_path / ".env"
    load_dotenv(env_path)

# =====================================================
# CONFIGURATION
# =====================================================

INPUT_APPSHEET_URL = "https://docs.google.com/spreadsheets/d/1ZcaFKwFiu79cyU3q0e7ds8EPfwaBaGICCsXHpX8iOl4/edit"
INPUT_TAB_NAME = "Formatted Output"

OUTPUT_APPSHEET_URL = "https://docs.google.com/spreadsheets/d/1UlD-jKkO9HEh_wAwFlcywlrBDYThpL6_s-_GtLOWmAg/edit"
OUTPUT_TAB_NAME = "AI Enhancements"

CREDENTIALS_PATH = "credentials.json"
CONFIG_FILE = "config.ini"

# =====================================================
# STRICT TARGET COLUMNS — only these will be written
# =====================================================

TARGET_COLUMNS = [
    "SP ID",
    "Name",
    "City",
    "Processed Date",
    "Poornanga",
    "High Skill",
    "Tamil Speaking",
    "Tier City",
    "Medical Professional",
    "Volunteer Experience",
    "Isha Family Connect",
    "English Proficiency",
    "Other Languages",
    "Prestigious Institution",
    "Undergrad/Postgrad",
    "Specialization",
    "Psychological Concerns",
    "Medical Concerns",
    "Highlights to SP Team",
    "Articulate",
    "General Willingness Level",
    "Seva Willingness Level",
    "Local Center Volunteering",
    "Ashram Volunteering",
    "Language Tags & Fluency",
    "Expertise / Skills",
    "Learnings from Past Seva Team Notes",
]

# =====================================================
# LOGGING SETUP
# =====================================================

def setup_logging():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    log_dir = config.get("LOGGING", "log_dir", fallback="logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    log_file = os.path.join(
        log_dir,
        f"ai_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logging.info("Logging initialized")

# =====================================================
# GOOGLE SHEETS HELPERS
# =====================================================

def get_gspread_client(credentials_path):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return gspread.authorize(creds)

def read_from_google_sheet(sheet_url, tab_name, credentials_path):
    try:
        logging.info(f"Reading from Google Sheet: {tab_name}")

        gc = get_gspread_client(credentials_path)
        sheet = gc.open_by_url(sheet_url)
        worksheet = sheet.worksheet(tab_name)

        data = worksheet.get_all_values()
        if not data:
            logging.warning("Sheet is empty")
            return pd.DataFrame()

        headers = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)

        logging.info(f"Loaded {len(df)} rows")
        return df

    except Exception:
        logging.exception("Failed to read Google Sheet")
        raise

def write_to_google_sheet(df, sheet_url, tab_name, credentials_path):
    try:
        logging.info(f"Safely appending results to: {tab_name}")

        # ── Enforce strict column set & order ──────────────────────────────
        # Add any missing target columns as empty strings, then keep only them
        for col in TARGET_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[TARGET_COLUMNS]
        # ───────────────────────────────────────────────────────────────────

        gc = get_gspread_client(credentials_path)
        sheet = gc.open_by_url(sheet_url)

        try:
            worksheet = sheet.worksheet(tab_name)
            logging.info("Found existing worksheet")
        except gspread.exceptions.WorksheetNotFound:
            logging.info("Creating new worksheet")
            worksheet = sheet.add_worksheet(title=tab_name, rows=1000, cols=50)

        df = df.fillna("").astype(str)
        headers = df.columns.tolist()
        values = df.values.tolist()

        existing_data = worksheet.get_all_values()

        # If sheet empty → write headers
        if not existing_data:
            logging.info("Sheet empty → writing headers")
            worksheet.append_row(headers)
            existing_ids = set()
        else:
            # Clean header values (strip spaces)
            existing_headers = [h.strip() for h in existing_data[0]]

            if "SP ID" in existing_headers:
                sp_id_index = existing_headers.index("SP ID")
                existing_ids = {
                    row[sp_id_index].strip()
                    for row in existing_data[1:]
                    if len(row) > sp_id_index
                }
            else:
                logging.warning("SP ID column not found in sheet header.")
                existing_ids = set()

        print("Rows before append:", len(worksheet.get_all_values()))

        new_rows = []
        for row in values:
            sp_id = str(row[0]).strip()  # SP ID is first column
            if sp_id not in existing_ids:
                new_rows.append(row)

        if new_rows:
            worksheet.append_rows(new_rows, value_input_option="RAW")
            logging.info(f"Appended {len(new_rows)} new records")
        else:
            logging.info("No new records to append")

        print("Rows after append:", len(worksheet.get_all_values()))

    except Exception:
        logging.exception("Failed to write Google Sheet")
        raise

# =====================================================
# MAIN PROCESS
# =====================================================

def main():
    setup_logging()
    logging.info("AI Candidate Summary process started")

    load_env()

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    if not OPENAI_API_KEY:
        logging.critical("OPENAI_API_KEY not found in .env file.")
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    df_candidates = read_from_google_sheet(
        INPUT_APPSHEET_URL,
        INPUT_TAB_NAME,
        CREDENTIALS_PATH
    )

    if df_candidates.empty:
        logging.error("No data found.")
        return

    # Build the AI tag list from TARGET_COLUMNS (everything after the first 4 fixed columns)
    AI_TAG_COLUMNS = TARGET_COLUMNS[4:]

    all_records = []

    for i, row in df_candidates.iterrows():
        sp_id = row.get("SP ID", f"Candidate-{i+1}")
        logging.info(f"Processing {i+1}/{len(df_candidates)} | SP ID: {sp_id}")

        candidate_dict = row.to_dict()

        tags_list = "\n".join(AI_TAG_COLUMNS)

        prompt = f"""
You are an assistant summarizing candidate profiles.

Candidate JSON:
{json.dumps(candidate_dict, indent=2)}

Tasks:
Return ONLY a valid JSON object with exactly these keys (no extra keys):
{tags_list}

Rules:
- For "Poornanga": provide a one-line justification.
- For "Tier City": identify the candidate's city from the data and classify it using this exact format: "<City Name> - Tier <number>".
  Examples: "Mumbai - Tier 1", "Roorke - Tier 3", "New York - Tier 1", "Minsk - Tier 2".
  Tier classification guide:
    Tier 1 = Major global/national metros (Mumbai, Delhi, Bangalore, Chennai, New York, London, Dubai, Shanghai, etc.)
    Tier 2 = Large regional cities (Pune, Hyderabad, Ahmedabad, Jaipur, Minsk, Düsseldorf, etc.)
    Tier 3 = Smaller towns and cities (Roorke, Howrah, smaller district towns, etc.)
  If city is unknown, write "No info found".
- For all other tags: provide a concise value or assessment.
- If no info is available for any other tag, write "No info found".
- Do NOT add any keys beyond the ones listed above.
"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a structured data extraction assistant. Return only valid JSON with the exact keys requested."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            content = response.choices[0].message.content

            try:
                start = content.index("{")
                end = content.rindex("}") + 1
                ai_tags = json.loads(content[start:end])
            except Exception:
                logging.warning(f"JSON parse failed for SP ID {sp_id}")
                ai_tags = {}

            record = {
                "SP ID": sp_id,
                "Name": candidate_dict.get("First Name") or candidate_dict.get("Name", ""),
                "City": candidate_dict.get("City", ""),
                "Processed Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # Only pick keys that exist in our TARGET_COLUMNS to avoid extra columns
            for col in AI_TAG_COLUMNS:
                record[col] = ai_tags.get(col, "No info found")

            all_records.append(record)

        except Exception:
            logging.exception(f"Processing failed for SP ID {sp_id}")
            record = {
                "SP ID": sp_id,
                "Name": candidate_dict.get("First Name", ""),
                "City": candidate_dict.get("City", ""),
                "Processed Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            for col in AI_TAG_COLUMNS:
                record[col] = "Processing failed"
            all_records.append(record)

    df_output = pd.DataFrame(all_records)

    write_to_google_sheet(
        df_output,
        OUTPUT_APPSHEET_URL,
        OUTPUT_TAB_NAME,
        CREDENTIALS_PATH
    )

    logging.info("Process completed successfully")

# =====================================================
# ENTRY POINT
# =====================================================

if __name__ == "__main__":
    main()
