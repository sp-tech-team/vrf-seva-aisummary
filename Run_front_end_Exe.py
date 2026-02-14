import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import datetime
import os
import threading
import configparser
import sys
import time

# ---------------------------------------------------------
# PATH HELPERS
# ---------------------------------------------------------
def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

APP_PATH = get_app_path()

# ---------------------------------------------------------
# LOAD CONFIG
# ---------------------------------------------------------
def load_config():
    config_path = os.path.join(APP_PATH, "config.ini")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.ini missing at: {config_path}")

    config = configparser.ConfigParser()
    config.read(config_path)
    return config

CONFIG = load_config()

# ---------------------------------------------------------
# DIRECTORIES
# ---------------------------------------------------------
DATA_DIR = CONFIG["paths"]["data_dir"]
DIST_FOLDER = os.path.join(APP_PATH, "dist")
LOG_FOLDER = os.path.join(APP_PATH, "logs")

os.makedirs(DIST_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------
# TIMESTAMP
# ---------------------------------------------------------
def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


# =========================================================
#                    TOOLTIP CLASS
# =========================================================
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, _event):
        if self.tip_window:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 30
        y += self.widget.winfo_rooty() + 20

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            tw,
            text=self.text,
            background="#FFFFDD",
            relief="solid",
            borderwidth=1,
            font=("Arial", 10)
        )
        label.pack(ipadx=3, ipady=3)

    def hide_tip(self, _event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# =========================================================
#                   EXECUTION WITH PROGRESS
# =========================================================
def run_exe_with_progress(exe_path, log_file, progress_bar, status_label):

    def task():
        try:
            progress_bar["value"] = 0
            status_label.config(text="Running...", fg="orange")

            with open(log_file, "w") as lf:
                process = subprocess.Popen(
                    exe_path,
                    stdout=lf,
                    stderr=lf,
                    shell=False
                )

                # animate
                while process.poll() is None:
                    progress_bar["value"] = (progress_bar["value"] + 3) % 100
                    time.sleep(0.1)

                return_code = process.returncode

            # -----------------------------------------------------
            # STRONG LOG-BASED ERROR DETECTION
            # -----------------------------------------------------
            log_has_error = False
            last_error_line = "Unknown error"

            try:
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    for line in lines:
                        low = line.lower()
                        if ("error" in low or "exception" in low or
                            "failed" in low or "traceback" in low):

                            log_has_error = True
                            last_error_line = line.strip()
                            break
            except:
                pass

            # -----------------------------------------------------
            # FAILURE CASE
            # -----------------------------------------------------
            if log_has_error:
                progress_bar["value"] = 0
                status_label.config(text="Failed ✗", fg="red")

                Tooltip(status_label, f"Error: {last_error_line}")

                # blinking
                for _ in range(3):
                    status_label.config(fg="red")
                    time.sleep(0.2)
                    status_label.config(fg="white")
                    time.sleep(0.2)
                    status_label.config(fg="red")

                # popup
                if messagebox.askyesno(
                    "Execution Failed",
                    f"Error detected in log.\n\nOpen log?\n{log_file}"
                ):
                    os.startfile(log_file)

                return

            # -----------------------------------------------------
            # SUCCESS CASE
            # -----------------------------------------------------
            progress_bar["value"] = 100
            status_label.config(text="Completed Successfully ✓", fg="green")

            messagebox.showinfo(
                "Execution Completed",
                f"Finished.\nLog saved:\n{log_file}"
            )

        except Exception as e:
            status_label.config(text="Failed ✗", fg="red")
            messagebox.showerror("Execution Error", str(e))

    threading.Thread(target=task, daemon=True).start()


# =========================================================
#                          GUI
# =========================================================
class App:
    def __init__(self, root):
        self.root = root
        root.title("VRF & Seva Allocation Tool")
        root.geometry("820x450")

        tk.Label(root, text="Select Operation Mode:", font=("Arial", 13)).pack(pady=10)

        self.mode_var = tk.StringVar()
        self.dropdown = ttk.Combobox(root, textvariable=self.mode_var, state="readonly")
        self.dropdown["values"] = ( "Seva Allocation", "Run VRF and Seva Allocation")
        self.dropdown.pack()

        self.button_frame = tk.Frame(root)
        self.button_frame.pack(pady=40)

        self.dropdown.bind("<<ComboboxSelected>>", self.update_ui)

        self.vrf_exe = CONFIG["paths"]["vrf_exe"]
        self.alloc_exe = CONFIG["paths"]["alloc_exe"]

    # ---------------------------------------------------------
    def update_ui(self, event=None):

        for w in self.button_frame.winfo_children():
            w.destroy()

        mode = self.mode_var.get()

        # ---------------------------------------------------------
        # VRF + ALLOCATION
        # ---------------------------------------------------------
        if mode == "Run VRF and Seva Allocation":

            # VRF row
            vrf_row = tk.Frame(self.button_frame)
            vrf_row.pack(pady=10)

            tk.Button(
                vrf_row,
                text="Run VRF",
                width=20,
                command=lambda: self.run_process(
                    self.vrf_exe,
                    "VRF_LOG",
                    self.vrf_progress,
                    self.vrf_label
                )
            ).pack(side="left", padx=10)

            self.vrf_progress = ttk.Progressbar(vrf_row, length=240, mode="determinate")
            self.vrf_progress.pack(side="left", padx=10)

            self.vrf_label = tk.Label(vrf_row, text="", font=("Arial", 11))
            self.vrf_label.pack(side="left", padx=5)

            # Allocation row
            alloc_row = tk.Frame(self.button_frame)
            alloc_row.pack(pady=10)

            tk.Button(
                alloc_row,
                text="Seva Allocation",
                width=20,
                command=lambda: self.run_process(
                    self.alloc_exe,
                    "ALLOCATION_LOG",
                    self.alloc_progress,
                    self.alloc_label
                )
            ).pack(side="left", padx=10)

            self.alloc_progress = ttk.Progressbar(alloc_row, length=240, mode="determinate")
            self.alloc_progress.pack(side="left", padx=10)

            self.alloc_label = tk.Label(alloc_row, text="", font=("Arial", 11))
            self.alloc_label.pack(side="left", padx=5)

        # ---------------------------------------------------------
        # ONLY ALLOCATION
        # ---------------------------------------------------------
        else:
            alloc_row = tk.Frame(self.button_frame)
            alloc_row.pack(pady=10)

            tk.Button(
                alloc_row,
                text="Seva Allocation",
                width=20,
                command=lambda: self.run_process(
                    self.alloc_exe,
                    "ALLOCATION_LOG",
                    self.alloc_progress,
                    self.alloc_label
                )
            ).pack(side="left", padx=10)

            self.alloc_progress = ttk.Progressbar(alloc_row, length=240, mode="determinate")
            self.alloc_progress.pack(side="left", padx=10)

            self.alloc_label = tk.Label(alloc_row, text="", font=("Arial", 11))
            self.alloc_label.pack(side="left", padx=5)

    # ---------------------------------------------------------
    def run_process(self, exe_filename, log_prefix, progress_bar, status_label):

        exe_path = os.path.join(DIST_FOLDER, exe_filename)

        if not os.path.exists(exe_path):
            messagebox.showerror("Error", f"EXE not found:\n{exe_path}")
            return

        log_file = os.path.join(
            LOG_FOLDER, f"{log_prefix}_{timestamp()}.log"
        )

        run_exe_with_progress(exe_path, log_file, progress_bar, status_label)


# =========================================================
# MAIN
# =========================================================



root = tk.Tk()
app = App(root)
root.main



loop()
