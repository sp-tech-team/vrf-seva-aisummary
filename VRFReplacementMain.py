import numpy as np
import pandas as pd
import gspread
import traceback
import os
import sys
import subprocess
from datetime import datetime
from google.oauth2.service_account import Credentials
import configparser

# =====================================================
# SETUP PATHS FOR BATCH_ALLOCATOR (EXE COMPATIBILITY)
# =====================================================
def setup_batch_allocator_path():
    """Ensure batch_allocator is in sys.path for both .py and .exe"""
    if getattr(sys, 'frozen', False):
        # Running as EXE
        base_dir = os.path.dirname(sys.executable)
    else:
        # Running as .py
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Add base directory to path
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

# Call BEFORE any batch_allocator imports
setup_batch_allocator_path()

from Libraries.Gspread_Library import GoogleSheetHandler
from Libraries.Concatenation_Library import Concatenation_Handler
from Libraries.LocalSheetManager import LocalSheetManager

# IMPORTANT: import vrf_indexer directly (NO subprocess)
from batch_allocator.vrf_indexer import main as vrf_indexer_main

# =====================================================
# DEDUPLICATION CONFIGURATION (Configurable inline)
# =====================================================
# Columns to use for deduplication when combining VRF data
DEDUP_COLUMNS = ["Request Name", "Job Title"]

# =====================================================
# LOGGING (EXE SAFE, TIMESTAMPED FILES)
# =====================================================
def setup_exe_logging():
    if getattr(sys, "frozen", False):
        if os.environ.get("VRF_LOG_INITIALIZED") == "1":
            return None
        os.environ["VRF_LOG_INITIALIZED"] = "1"

    base_dir = os.path.dirname(
        sys.executable if getattr(sys, "frozen", False)
        else os.path.abspath(__file__)
    )
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Create timestamped log file name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"vrf_run_{timestamp}.log")
    
    log_fp = open(log_file, "a", encoding="utf-8", errors="replace")

    sys.stdout = log_fp
    sys.stderr = log_fp

    print("=" * 60)
    print("VRFReplacementMain STARTED")
    print(f"PID: {os.getpid()}")
    print(f"Time: {datetime.now()}")
    print(f"Log File: {log_file}")
    print("=" * 60, flush=True)

    return log_fp


def get_app_path():
    if getattr(sys, 'frozen', False):
        # Running as an EXE
        return os.path.dirname(sys.executable)
    else:
        # Running as a .py file
        return os.path.dirname(os.path.abspath(__file__))


def load_config():
    config = configparser.ConfigParser()
    base_path = get_app_path()
    print(f"\n--- Starting from: {base_path} ---", flush=True)
    config_path = os.path.join(base_path, "config.ini")
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.ini not found at: {config_path}")

    config.read(config_path)
    return config        


# --- Global Logging List ---
execution_log = []

# Global sheet manager placeholder (will be initialized in main)
SHEET_MANAGER = None

def run_step(step_name, func, *args, **kwargs):
    """ Helper to run a function, track its status, and log the result. """
    print(f"\n--- Starting {step_name} ---", flush=True)
    start = datetime.now()
    
    try:
        result = func(*args, **kwargs)
        if result is False:
            status = False
            error_msg = "Function returned 'False' (Check internal logs)"
        else:
            status = True
            error_msg = None
            
    except Exception as e:
        status = False
        error_msg = str(e)
        print(f"[ERROR] {step_name} failed", flush=True)
        traceback.print_exc()

    duration = datetime.now() - start
    print(f"--- Finished {step_name} (Time: {duration.total_seconds():.2f}s) ---\n", flush=True)
    
    execution_log.append({
        "name": step_name,
        "status": status,
        "error": error_msg
    })

# ==========================================
# FUNCTION DEFINITIONS
# ==========================================

def Concatenate_Skills_By_RequestName(sheet_url, input_tab_name, output_tab_name, credentials_path, local_cleaned_paths=[]):
    """ 
    Step 1: Fetches, concatenates skills, updates GSheet, AND saves 'vrf_data_cleaned.csv' to multiple locations.
    """
    try:
        # --- Use local cached read first ---
        global SHEET_MANAGER
        df_in = None
        if SHEET_MANAGER is not None:
            df_in = SHEET_MANAGER.load_tab_from_cache(sheet_url, input_tab_name)
            if df_in is None:
                df_in = SHEET_MANAGER.ensure_local_copy(sheet_url, [input_tab_name])[input_tab_name]
        else:
            # Fallback to direct read if SHEET_MANAGER not available
            sheet_handler = GoogleSheetHandler(credentials_path)
            df_in = sheet_handler.get_sheet_as_dataframe(sheet_url, input_tab_name)

        print(f"Fetching data from '{input_tab_name}'...", flush=True)
        if df_in is None or (hasattr(df_in, 'empty') and df_in.empty):
            print("Input data is empty.", flush=True)
            return False

        df = df_in.copy()
        columns_to_fill = ["Request Name"]
        columns_to_concatenate = ["Skills/Keywords", "Educational Qualification"]

        df = Concatenation_Handler.front_fill_columns(df, columns_to_fill)
        df = Concatenation_Handler.convert_columns_to_string(df, columns_to_concatenate)
        df = Concatenation_Handler.concatenate_method_for_Gspread(df, 'Request Name', columns_to_concatenate)
        df_result = df.drop_duplicates(subset=["Request Name"]).reset_index(drop=True)

        desired_column_order = [
            "Request Name", "Job Title", "Job Description", "Gender Preference",
            "# of Volunteers", "Work Experience Needed?", "Number of Years",
            "Skills/Keywords", "Educational Qualification", "Comments",
            "Please mention any other comments about Seva timings", "Department",
            "Skills", "Languages"
        ]
        
        # Keep all columns that exist in the dataframe
        existing_cols = [col for col in desired_column_order if col in df_result.columns]
        
        # Add any missing columns with empty values for the indexer
        missing_cols = ["Skills", "Languages"]
        for col in missing_cols:
            if col not in df_result.columns:
                df_result[col] = ""
                print(f"Added missing column '{col}' with empty values", flush=True)
        
        df_result = df_result[existing_cols + [col for col in missing_cols if col not in existing_cols]]

        print(f"Concatenation complete. Writing {len(df_result)} rows to '{output_tab_name}'...", flush=True)
        GoogleSheetHandler(credentials_path).write_dataframe_to_sheet(sheet_url, df_result, output_tab_name)

        # --- Save Cleaned Data to Multiple Locations ---
        if local_cleaned_paths:
            for path in local_cleaned_paths:
                output_dir = os.path.dirname(path)
                if not os.path.exists(output_dir): 
                    os.makedirs(output_dir)
                
                print(f"Saving Cleaned Data to: {path}", flush=True)
                df_result.to_csv(path, index=False, encoding='utf-8')

        return True

    except Exception as e:
        print(f"Error in Step 1: {e}", flush=True)
        traceback.print_exc()
        return False


def Sync_VRF_To_AppSheet(source_sheet_url, source_tab_name, target_sheet_url, target_tab_name, credentials_path):
    """ Step 2: Syncs 'Skills Combined Output' to 'New vrf'. """
    try:
        global SHEET_MANAGER

        print(f"Reading Source: '{source_tab_name}'...", flush=True)
        if SHEET_MANAGER is not None:
            df_source = SHEET_MANAGER.load_tab_from_cache(source_sheet_url, source_tab_name)
            if df_source is None:
                df_source = SHEET_MANAGER.ensure_local_copy(source_sheet_url, [source_tab_name])[source_tab_name]
        else:
            df_source = GoogleSheetHandler(credentials_path).get_sheet_as_dataframe(source_sheet_url, source_tab_name)

        print(f"Reading Target: '{target_tab_name}'...", flush=True)
        if SHEET_MANAGER is not None:
            df_target = SHEET_MANAGER.load_tab_from_cache(target_sheet_url, target_tab_name)
            if df_target is None:
                df_target = SHEET_MANAGER.ensure_local_copy(target_sheet_url, [target_tab_name])[target_tab_name]
        else:
            df_target = GoogleSheetHandler(credentials_path).get_sheet_as_dataframe(target_sheet_url, target_tab_name)

        count_before = len(df_target) if df_target is not None else 0
        if df_source is None or (hasattr(df_source, 'empty') and df_source.empty):
            print("Source is empty. Nothing to sync.", flush=True)
            return True

        source_ids = df_source.iloc[:, 0].astype(str).str.strip()
        
        if df_target is None or (hasattr(df_target, 'empty') and df_target.empty):
            print("Target is empty. Appending all rows.", flush=True)
            df_to_upload = df_source.copy()
        else:
            target_ids = set(df_target.iloc[:, 0].astype(str).str.strip())
            df_to_upload = df_source[~source_ids.isin(target_ids)].copy()

        count_to_add = len(df_to_upload)
        if count_to_add > 0:
            print(f"Identified {count_to_add} new VRF requests to append.", flush=True)
            GoogleSheetHandler(credentials_path).append_to_sheet(target_sheet_url, df_to_upload, target_tab_name)
        else:
            print("No new VRF requests found.", flush=True)

        print("-" * 30, flush=True)
        print(f"Stats Report for '{target_tab_name}':", flush=True)
        print(f"1. Total Rows Before Sync  : {count_before}", flush=True)
        print(f"2. New Rows Added          : {count_to_add}", flush=True)
        print(f"3. Total Rows After Sync   : {count_before + count_to_add}", flush=True)
        print("-" * 30, flush=True)
        return True
    except Exception as e:
        print(f"Error in Step 2: {e}", flush=True)
        traceback.print_exc()
        return False

def Merge_Old_And_New(sheet_url, old_tab, new_tab, merged_tab, credentials_path):
    """ Step 3: Merges 'Old vrf' and 'New vrf' into 'Merged VRF's'. """
    try:
        global SHEET_MANAGER

        print(f"Reading '{old_tab}' and '{new_tab}'...", flush=True)
        if SHEET_MANAGER is not None:
            df_old = SHEET_MANAGER.load_tab_from_cache(sheet_url, old_tab)
            df_new = SHEET_MANAGER.load_tab_from_cache(sheet_url, new_tab)

            # If any missing, fetch both to ensure consistency
            if df_old is None or df_new is None:
                local_data = SHEET_MANAGER.ensure_local_copy(sheet_url, [old_tab, new_tab])
                df_old = local_data[old_tab]
                df_new = local_data[new_tab]
        else:
            df_old = GoogleSheetHandler(credentials_path).get_sheet_as_dataframe(sheet_url, old_tab)
            df_new = GoogleSheetHandler(credentials_path).get_sheet_as_dataframe(sheet_url, new_tab)

        if df_old is None:
            df_old = pd.DataFrame()
        if df_new is None:
            df_new = pd.DataFrame()

        df_old['VRF ID Status'] = "Old VRF ID"
        df_new['VRF ID Status'] = "New VRF ID"

        df_combined = pd.concat([df_old, df_new], ignore_index=True)
        id_col = df_combined.columns[0]
        
        print("Merging and handling conflicts...", flush=True)
        df_merged = df_combined.drop_duplicates(subset=[id_col], keep='last').reset_index(drop=True)
        df_merged = df_merged[df_merged[id_col].astype(str).str.strip() != ""]

        print(f"Writing {len(df_merged)} rows to '{merged_tab}'...", flush=True)
        GoogleSheetHandler(credentials_path).write_dataframe_to_sheet(sheet_url, df_merged, merged_tab)
        return True

    except Exception as e:
        print(f"Error in Step 3: {e}", flush=True)
        traceback.print_exc()
        return False

def Update_Main_VRF_Table(sheet_url, merged_tab, main_vrf_tab, credentials_path):
    """ Step 4: Safe Replace Logic (Merged + Orphans). """
    try:
        global SHEET_MANAGER

        print(f"Reading '{merged_tab}' and '{main_vrf_tab}'...", flush=True)
        if SHEET_MANAGER is not None:
            df_merged = SHEET_MANAGER.load_tab_from_cache(sheet_url, merged_tab)
            df_main = SHEET_MANAGER.load_tab_from_cache(sheet_url, main_vrf_tab)

            if df_merged is None or df_main is None:
                cached = SHEET_MANAGER.ensure_local_copy(sheet_url, [merged_tab, main_vrf_tab])
                df_merged = cached[merged_tab]
                df_main = cached[main_vrf_tab]
        else:
            df_merged = GoogleSheetHandler(credentials_path).get_sheet_as_dataframe(sheet_url, merged_tab)
            df_main = GoogleSheetHandler(credentials_path).get_sheet_as_dataframe(sheet_url, main_vrf_tab)

        if df_merged is None or (hasattr(df_merged, 'empty') and df_merged.empty):
            print("Merged source is empty. No updates applied.", flush=True)
            return True

        if df_main is None:
            df_main = pd.DataFrame()

        id_col = df_merged.columns[0]
        print(f"Using Unique Key: '{id_col}'", flush=True)

        df_merged[id_col] = df_merged[id_col].astype(str).str.strip()
        if id_col in df_main.columns:
            df_main[id_col] = df_main[id_col].astype(str).str.strip()
        else:
            df_main[id_col] = ""

        merged_ids = set(df_merged[id_col])
        df_orphans = df_main[~df_main[id_col].isin(merged_ids)].copy()
        
        print(f"Updates/New: {len(df_merged)} | Preserved Orphans: {len(df_orphans)}", flush=True)

        df_final = pd.concat([df_merged, df_orphans], ignore_index=True)
        
        print(f"Final Count: {len(df_final)}. Writing safely to '{main_vrf_tab}' starting at Row 2...", flush=True)

        sheet = GoogleSheetHandler(credentials_path).client.open_by_url(sheet_url)
        ws = sheet.worksheet(main_vrf_tab)

        df_final = df_final.fillna("").replace({pd.NA: ""})
        data_values = df_final.values.tolist()

        if data_values:
            try:
                ws.update(data_values, "A2", value_input_option="RAW")
            except Exception:
                ws.update("A2", data_values, value_input_option="RAW")
        
        last_updated_row = 1 + len(data_values) 
        total_rows_in_sheet = ws.row_count
        
        if total_rows_in_sheet > last_updated_row:
            print(f"Clearing residual data from row {last_updated_row + 1} to {total_rows_in_sheet}...", flush=True)
            ws.batch_clear([f"A{last_updated_row + 1}:{total_rows_in_sheet}"])

        return True

    except Exception as e:
        print(f"Error in Step 4: {e}", flush=True)
        traceback.print_exc()
        return False

def Combine_And_Index_VRF_Data(config, vrf_input_sheet_url, vrf_input_tab, 
                               old_cleaned_csv_path, generic_jobs_csv_path, 
                               index_output_csv_path, credentials_path):
    """
    Step 5: Combines old VRF (from Input tab), new cleaned VRF, and generic jobs,
    then saves the combined data and indexes it to Pinecone.
    
    Args:
        config: Configuration object
        vrf_input_sheet_url: URL of the sheet containing the Input tab
        vrf_input_tab: Name of the tab with raw VRF data (e.g., "Input")
        cleaned_csv_path: Path to the cleaned VRF CSV (new data)
        generic_jobs_csv_path: Path to the generic jobs CSV
        index_output_csv_path: Path where combined data should be saved for indexing
        credentials_path: Path to Google credentials JSON
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        global SHEET_MANAGER
        
        # --- Step 5.1: Read New VRF Data from Input Tab ---
        print(f"[Step 5.1] Fetching New VRF data from clean CSV '{NEW_VRF_CLEANED_CSV}'...", flush=True)
        
        if os.path.exists(NEW_VRF_CLEANED_CSV):
            df_new_vrf = pd.read_csv(NEW_VRF_CLEANED_CSV)
            print(f"  -> Loaded {len(df_new_vrf)} rows from new cleaned CSV", flush=True)
        else:
            print(f"  -> WARNING: New VRF Cleaned CSV not found at {NEW_CRF_CLEANED_CSV}, using empty DataFrame", flush=True)
            df_new_vrf = pd.DataFrame()
        print(f"  -> Loaded {len(df_new_vrf)} rows from new VRF csv)", flush=True)
        
        # --- Step 5.2: Read Old Cleaned VRF Data ---
        print(f"[Step 5.2] Reading NEW cleaned VRF data from: {old_cleaned_csv_path}", flush=True)
        if os.path.exists(old_cleaned_csv_path):
            df_old_vrf = pd.read_csv(old_cleaned_csv_path)
            print(f"  -> Loaded {len(df_old_vrf)} rows from cleaned CSV", flush=True)
        else:
            print(f"  -> WARNING: Cleaned CSV not found at {old_cleaned_csv_path}, using empty DataFrame", flush=True)
            df_old_vrf = pd.DataFrame()
        
        # --- Step 5.3: Read Generic Jobs Data ---
        print(f"[Step 5.3] Reading generic jobs data from: {generic_jobs_csv_path}", flush=True)
        if os.path.exists(generic_jobs_csv_path):
            df_generic_jobs = pd.read_csv(generic_jobs_csv_path)
            print(f"  -> Loaded {len(df_generic_jobs)} rows from generic jobs CSV", flush=True)
        else:
            print(f"  -> WARNING: Generic jobs CSV not found at {generic_jobs_csv_path}, using empty DataFrame", flush=True)
            df_generic_jobs = pd.DataFrame()
        
        # --- Step 5.4: Combine All Three DataFrames ---
        print(f"[Step 5.4] Combining all VRF data sources...", flush=True)
        
        # Concatenate all dataframes
        all_dfs = [df_new_vrf, df_old_vrf, df_generic_jobs]
        valid_dfs = [df for df in all_dfs if df is not None and not df.empty]
        
        if not valid_dfs:
            print("  -> ERROR: All data sources are empty!", flush=True)
            return False
        
        df_combined = pd.concat(valid_dfs, ignore_index=True)
        print(f"  -> Combined total: {len(df_combined)} rows", flush=True)
        
        # --- Step 5.5: Deduplicate Based on Configured Columns ---
        print(f"[Step 5.5] Deduplicating based on columns: {DEDUP_COLUMNS}", flush=True)
        
        # Verify deduplication columns exist
        missing_cols = [col for col in DEDUP_COLUMNS if col not in df_combined.columns]
        if missing_cols:
            print(f"  -> WARNING: Deduplication columns {missing_cols} not found in data", flush=True)
            print(f"  -> Available columns: {list(df_combined.columns)}", flush=True)
            # Use only available columns for deduplication
            valid_dedup_cols = [col for col in DEDUP_COLUMNS if col in df_combined.columns]
            if not valid_dedup_cols:
                print("  -> ERROR: No valid deduplication columns found, skipping deduplication", flush=True)
            else:
                print(f"  -> Using available columns for deduplication: {valid_dedup_cols}", flush=True)
                df_combined = df_combined.drop_duplicates(subset=valid_dedup_cols, keep='last').reset_index(drop=True)
        else:
            df_combined = df_combined.drop_duplicates(subset=DEDUP_COLUMNS, keep='last').reset_index(drop=True)
        
        print(f"  -> After deduplication: {len(df_combined)} rows", flush=True)
        
        # --- Step 5.6: Save Combined Data for Indexing ---
        print(f"[Step 5.6] Saving combined data to: {index_output_csv_path}", flush=True)
        output_dir = os.path.dirname(index_output_csv_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        df_combined.to_csv(index_output_csv_path, index=False, encoding='utf-8')
        print(f"  -> Successfully saved {len(df_combined)} rows to index CSV", flush=True)
        
        # --- Step 5.7: Run VRF Indexer ---
        print("[Step 5.7] Running VRF Indexer using direct import...", flush=True)
        
        original_argv = sys.argv.copy()
        sys.argv = [
            'vrf_indexer',
            '--vrf_data_cleaned_out_csv', index_output_csv_path,  # Use the combined CSV
            '--generic_jobs_csv', generic_jobs_csv_path,
            '--pinecone_index_name', 'vrf-vectors'
        ]
        
        try:
            vrf_indexer_main()
            print("  -> VRF Indexer completed successfully", flush=True)
        finally:
            sys.argv = original_argv
        
        return True

    except Exception as e:
        print(f"Error in Step 5: {e}", flush=True)
        traceback.print_exc()
        return False

# ==========================================
# MAIN EXECUTION BLOCK
# ==========================================

if __name__ == "__main__":
    
    # Initialize timestamped logging
    log_fp = setup_exe_logging()
    
    try:
        # --- CONFIGURATION ---
        start_time = datetime.now()
        config = load_config()
        
        CREDENTIALS_PATH = config["paths"]["credentials_json"]
        
        # --- PATHS (SYNCING TWO FOLDERS) ---
        BATCH_ALLOCATOR_ROOT = config["paths"]["base_dir"]
        CHECKOUT_ROOT = config["paths"]["CHECKOUT_ROOT"]
        NEW_VRF_CLEANED_CSV = config["paths"]["new_vrf_cleaned_csv"]
        # Define file names
        FILE_RAW = "new_vrf_data_raw.csv"
        FILE_CLEANED = "new_vrf_data_cleaned.csv"

        # Paths for cleaned data (created in Step 1)
        PATHS_CLEANED = [
            os.path.join(BATCH_ALLOCATOR_ROOT, "data", FILE_CLEANED),
            os.path.join(CHECKOUT_ROOT, "data", FILE_CLEANED)
        ]

        # Paths from config for Step 5
        OLD_CLEANED_CSV_PATH = config["paths"]["old_vrf_cleaned_csv"]
        GENERIC_JOBS_CSV_PATH = config["paths"]["generic_jobs_csv"]
        INDEX_CSV_PATH = config["paths"]["index_csv"]

        # VRF Input Sheet (Source)
        VRF_SHEET_URL = "https://docs.google.com/spreadsheets/d/1i0ANT5-tamlo6YX9uuMTUwayzL31YEmpgC6qQ-0y7jI/edit?gid=1288139751#gid=1288139751"
        INPUT_TAB = "Input"
        OUTPUT_TAB = "Skills Combined Output"
        
        # AppSheet Backend (Target) - PRODUCTION URL
        APPSHEET_BACKEND_URL = "https://docs.google.com/spreadsheets/d/1UlD-jKkO9HEh_wAwFlcywlrBDYThpL6_s-_GtLOWmAg/edit?gid=1578071586#gid=1578071586"
        
        # Tab Definitions
        TAB_NEW_VRF = "New vrf"
        TAB_OLD_VRF = "Old vrf"
        TAB_MERGED_VRF = "Merged VRF's"
        TAB_MAIN_VRF = "vrf"

        print("\n--- VRF Replacement Pipeline Initialized ---\n", flush=True)
        print(f"Deduplication configured for columns: {DEDUP_COLUMNS}", flush=True)

        # Initialize LocalSheetManager (cache + batch reads)
        SHEET_MANAGER = LocalSheetManager(
            credentials_file=CREDENTIALS_PATH,
            cache_dir=os.path.join(get_app_path(), "sheet_cache"),
            ttl_seconds=3600  # 1 hour cache
        )

        # Step 1: Concatenate and Save 'vrf_data_cleaned.csv'
        run_step(
            "Step 1: Concatenate Skills & Save Cleaned CSVs",
            Concatenate_Skills_By_RequestName,
            sheet_url=VRF_SHEET_URL,
            input_tab_name=INPUT_TAB,
            output_tab_name=OUTPUT_TAB,
            credentials_path=CREDENTIALS_PATH,
            local_cleaned_paths=PATHS_CLEANED
        )

        # Step 2: Sync to AppSheet
        run_step(
            "Step 2: Sync to 'New vrf'",
            Sync_VRF_To_AppSheet,
            source_sheet_url=VRF_SHEET_URL,
            source_tab_name=OUTPUT_TAB,
            target_sheet_url=APPSHEET_BACKEND_URL,
            target_tab_name=TAB_NEW_VRF,
            credentials_path=CREDENTIALS_PATH
        )

        # Step 3: Merge Logic
        run_step(
            "Step 3: Merge Old & New to 'Merged VRF's'",
            Merge_Old_And_New,
            sheet_url=APPSHEET_BACKEND_URL,
            old_tab=TAB_OLD_VRF,
            new_tab=TAB_NEW_VRF,
            merged_tab=TAB_MERGED_VRF,
            credentials_path=CREDENTIALS_PATH
        )

        # Step 4: Safe Replace Logic
        run_step(
            "Step 4: Update Main 'vrf' Table",
            Update_Main_VRF_Table,
            sheet_url=APPSHEET_BACKEND_URL,
            merged_tab=TAB_MERGED_VRF,
            main_vrf_tab=TAB_MAIN_VRF,
            credentials_path=CREDENTIALS_PATH
        )

        # Step 5: Combine All Data Sources and Index to Pinecone
        run_step(
            "Step 5: Combine VRF Data & Update Pinecone Vectors",
            Combine_And_Index_VRF_Data,
            config=config,
            vrf_input_sheet_url=VRF_SHEET_URL,
            vrf_input_tab=INPUT_TAB,
            old_cleaned_csv_path=OLD_CLEANED_CSV_PATH,
            generic_jobs_csv_path=GENERIC_JOBS_CSV_PATH,
            index_output_csv_path=INDEX_CSV_PATH,
            credentials_path=CREDENTIALS_PATH
        )

        # Final Summary
        Concatenation_Handler.Summarize_Execution(execution_log)

        # Timing
        end_time = datetime.now()
        duration = end_time - start_time
        total_seconds = duration.total_seconds()
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        print(f"Total execution time: {int(hours):02}:{int(minutes):02}:{int(seconds):02} (HH:MM:SS)", flush=True)

    except Exception:
        print("[FATAL] Unhandled exception", flush=True)
        traceback.print_exc()

    finally:
        print("=== EXE FINISHED ===", flush=True)
        if log_fp:
            log_fp.flush()   # DO NOT CLOSE