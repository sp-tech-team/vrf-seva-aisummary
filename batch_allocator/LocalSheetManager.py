# Libraries/LocalSheetManager.py
import os
import time
import json
import errno
import hashlib
import shutil
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime, timedelta

# Import your GoogleSheetHandler (the updated file above)
from Libraries.Gspread_Library import GoogleSheetHandler

# Local cache config
DEFAULT_CACHE_DIR = os.path.join(os.getcwd(), "sheet_cache")
DEFAULT_TTL_SECONDS = 60 * 60  # 1 hour default TTL for cache
PARQUET_AVAILABLE = True
try:
    import pyarrow  # noqa: F401
except Exception:
    PARQUET_AVAILABLE = False

def _ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

def _safe_filename(s: str) -> str:
    # Make a short deterministic filename from a sheet url + tab name
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    safe = "".join(ch if ch.isalnum() else "_" for ch in s)[:40]
    return f"{safe}_{h[:10]}"

class LocalSheetManager:
    def __init__(self, credentials_file: str, cache_dir: str = DEFAULT_CACHE_DIR, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        """
        Manages downloading Google Sheet tabs in batch and caching locally.
        - credentials_file: path to service account JSON
        - cache_dir: local folder to store parquet/csv caches
        - ttl_seconds: cache time-to-live in seconds
        """
        self.handler = GoogleSheetHandler(credentials_file)
        self.cache_dir = cache_dir
        _ensure_dir(self.cache_dir)
        self.ttl = ttl_seconds

    def _cache_paths(self, sheet_url: str, tab_name: str):
        label = f"{sheet_url}::: {tab_name}"
        fname = _safe_filename(label)
        if PARQUET_AVAILABLE:
            return os.path.join(self.cache_dir, fname + ".parquet")
        else:
            return os.path.join(self.cache_dir, fname + ".csv")

    def _is_fresh(self, path: str):
        if not os.path.exists(path):
            return False
        mod = datetime.fromtimestamp(os.path.getmtime(path))
        return (datetime.now() - mod).total_seconds() <= self.ttl

    def fetch_and_cache_tabs(self, sheet_url: str, tab_names: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Batch fetch a set of tab_names (works with gspread.batch_get when possible).
        Returns dict: {tab_name: DataFrame}
        """
        # Open spreadsheet safely via handler
        sheet = self.handler.client.open_by_url(sheet_url)

        # Build list of A1 ranges; we will request whole sheets by sheet name (gspread accepts "'Sheet'!A:Z" style)
        # But we don't know how many columns — safe approach: request entire sheet by sheet name only via worksheet.batch_get?
        # gspread Spreadsheet.batch_get accepts list of ranges; using sheet.worksheet(...).get_all_values is per-sheet.
        # To reduce calls, we try sheet.batch_get with named ranges: "'SheetName'" works in Sheets API but gspread's batch_get expects A1 ranges.
        # So we'll attempt to use gspread's worksheet objects but still minimize duplicate metadata calls by reusing worksheet objects.

        results = {}
        for tab in tab_names:
            cache_path = self._cache_paths(sheet_url, tab)
            if self._is_fresh(cache_path):
                # Load from cache
                try:
                    if PARQUET_AVAILABLE and cache_path.endswith(".parquet"):
                        df = pd.read_parquet(cache_path)
                    else:
                        df = pd.read_csv(cache_path)
                    results[tab] = df
                    continue
                except Exception as e:
                    print(f"[LocalSheetManager] Failed to load cache for {tab} ({e}), refetching...")

            # Not fresh or failed to load - fetch
            try:
                # Use handler.get_sheet_as_dataframe which itself is safe-wrapped
                df = self.handler.get_sheet_as_dataframe(sheet_url, tab)
            except Exception as e:
                # If direct worksheet fetch fails, attempt a secondary path (list worksheets and match)
                print(f"[LocalSheetManager] get_sheet_as_dataframe failed for tab '{tab}': {e}. Trying fallback.")
                try:
                    worksheet = sheet.worksheet(tab)
                    data = worksheet.get_all_values()
                    if not data or len(data) < 1:
                        df = pd.DataFrame()
                    else:
                        df = pd.DataFrame(data[1:], columns=data[0])
                        df.replace(["", "nan"], np.nan, inplace=True)
                        df = df.convert_dtypes()
                except Exception as e2:
                    print(f"[LocalSheetManager] Fallback also failed for '{tab}': {e2}. Returning empty DataFrame.")
                    df = pd.DataFrame()

            # Save to cache (atomic write)
            try:
                tmp = cache_path + ".tmp"
                if PARQUET_AVAILABLE and cache_path.endswith(".parquet"):
                    df.to_parquet(tmp)
                else:
                    df.to_csv(tmp, index=False)
                shutil.move(tmp, cache_path)
            except Exception as e:
                print(f"[LocalSheetManager] Failed to write cache {cache_path}: {e}")

            results[tab] = df

        return results

    def load_tab_from_cache(self, sheet_url: str, tab_name: str) -> Optional[pd.DataFrame]:
        """Load a single tab from cache if fresh; otherwise returns None."""
        cache_path = self._cache_paths(sheet_url, tab_name)
        if self._is_fresh(cache_path):
            try:
                if PARQUET_AVAILABLE and cache_path.endswith(".parquet"):
                    return pd.read_parquet(cache_path)
                else:
                    return pd.read_csv(cache_path)
            except Exception as e:
                print(f"[LocalSheetManager] Failed to read cache for {tab_name}: {e}")
                return None
        return None

    def ensure_local_copy(self, sheet_url: str, tab_names: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Ensure local cache exists for every tab in tab_names.
        Fetches only missing/stale tabs and returns dict {tab: df}.
        """
        return self.fetch_and_cache_tabs(sheet_url, tab_names)

    def upload_dataframe(self, sheet_url: str, df: pd.DataFrame, worksheet_name: str):
        """
        Upload a DataFrame back to Google (single write). Use GoogleSheetHandler.write_dataframe_to_sheet which is safe.
        """
        self.handler.write_dataframe_to_sheet(sheet_url, df, worksheet_name)
