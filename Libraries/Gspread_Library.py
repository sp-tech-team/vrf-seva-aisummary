# Libraries/Gspread_Library.py
import time
import numpy as np
import pandas as pd
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials


# ---------------- SAFE CALL WRAPPER ----------------
def _safe_call(func, *args, max_retries=6, base_sleep=2, **kwargs):
    """
    A safe retry wrapper for gspread API calls.
    Retries on 429 (rate limits), raises for all other errors.
    """
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            if "429" in str(e):
                wait = base_sleep ** attempt
                print(f"[Gspread Retry] 429 detected. Sleeping {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            else:
                raise
    raise RuntimeError("gspread API returned 429 repeatedly.")



# ---------------- GOOGLE SHEET HANDLER ----------------
class GoogleSheetHandler:
    """
    Unified clean handler for interacting with Google Sheets:
    - read as dataframe
    - write entire dataframe
    - append rows
    Zero circular imports. 100% safe for PyInstaller.
    """

    def __init__(self, credentials_file: str, scopes=None):
        if scopes is None:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        self.creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        self.client = gspread.authorize(self.creds)



    # ------------- READ ----------------
    def get_sheet_as_dataframe(self, sheet_url: str, worksheet_name: str = None) -> pd.DataFrame:
        sheet = _safe_call(self.client.open_by_url, sheet_url)

        if worksheet_name:
            worksheet = _safe_call(sheet.worksheet, worksheet_name)
        else:
            worksheet = _safe_call(sheet.get_worksheet, 0)

        data = _safe_call(worksheet.get_all_values)

        if not data or len(data) < 1:
            return pd.DataFrame()

        df = pd.DataFrame(data[1:], columns=data[0])
        df.replace(["", "nan"], np.nan, inplace=True)
        df = df.convert_dtypes()
        return df



    # ------------- WRITE FULL DATAFRAME ----------------
    def write_dataframe_to_sheet(self, sheet_url: str, df: pd.DataFrame, worksheet_name: str = None):

        # Convert integer → object to allow empty strings
        for col in df.columns:
            if pd.api.types.is_integer_dtype(df[col].dtype):
                df[col] = df[col].astype("object")

        df = df.fillna("").replace({pd.NA: ""})

        sheet = _safe_call(self.client.open_by_url, sheet_url)

        # Select or create worksheet
        try:
            if worksheet_name:
                worksheet = _safe_call(sheet.worksheet, worksheet_name)
            else:
                worksheet = _safe_call(sheet.get_worksheet, 0)
        except Exception:
            if worksheet_name:
                worksheet = _safe_call(
                    sheet.add_worksheet,
                    title=worksheet_name,
                    rows=str(len(df) + 1),
                    cols=str(len(df.columns))
                )
            else:
                worksheet = _safe_call(sheet.get_worksheet, 0)

        _safe_call(worksheet.clear)
        _safe_call(worksheet.update, [df.columns.tolist()] + df.values.tolist())



    # ------------- APPEND ROWS ----------------
    def append_to_sheet(self, sheet_url: str, df: pd.DataFrame, worksheet_name: str = None):

        for col in df.columns:
            if pd.api.types.is_integer_dtype(df[col].dtype):
                df[col] = df[col].astype("object")

        df = df.fillna("").replace({pd.NA: ""})

        sheet = _safe_call(self.client.open_by_url, sheet_url)

        try:
            if worksheet_name:
                worksheet = _safe_call(sheet.worksheet, worksheet_name)
            else:
                worksheet = _safe_call(sheet.get_worksheet, 0)
        except Exception:
            if worksheet_name:
                worksheet = _safe_call(
                    sheet.add_worksheet,
                    title=worksheet_name,
                    rows=str(len(df) + 1),
                    cols=str(len(df.columns))
                )
            else:
                worksheet = _safe_call(sheet.get_worksheet, 0)

        _safe_call(worksheet.append_rows, df.values.tolist(), value_input_option="RAW")
