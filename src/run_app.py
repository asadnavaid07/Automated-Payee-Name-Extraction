import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List
import time
from datetime import datetime

from seed_checks import parse_statement, CheckTransaction
from fetch_images import main as fetch_images_main


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Check Payee Automation - Desktop")
        self.minsize(1000, 700)

        self.selected_file_path: str | None = None
        self.parsed_checks: List[CheckTransaction] = []
        self.final_csv_path: str | None = None
        
        # Progress tracking variables
        self.total_checks = 0
        self.processed_checks = 0
        self.successful_checks = 0
        self.failed_checks = 0
        self.current_operation = ""
        self.start_time = None
        self.login_required = False

        self._build_ui()

    def _build_ui(self) -> None:
        # Main container with padding
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header section
        header_frame = ttk.LabelFrame(main_frame, text="📁 File Selection", padding=10)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        file_frame = ttk.Frame(header_frame)
        file_frame.pack(fill=tk.X)
        
        self.select_btn = ttk.Button(file_frame, text="📂 Select Bank Statement CSV", command=self._on_select_csv)
        self.select_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.file_label_var = tk.StringVar(value="No file selected")
        self.file_label = ttk.Label(file_frame, textvariable=self.file_label_var, foreground="gray")
        self.file_label.pack(side=tk.LEFT, padx=10)
        
        self.process_btn = ttk.Button(file_frame, text="🚀 Start Processing", command=self._on_process, state=tk.DISABLED)
        self.process_btn.pack(side=tk.RIGHT)
        
        # Progress section
        progress_frame = ttk.LabelFrame(main_frame, text="📊 Processing Progress", padding=10)
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Progress grid
        progress_grid = ttk.Frame(progress_frame)
        progress_grid.pack(fill=tk.X)
        
        # Current operation
        ttk.Label(progress_grid, text="Current Operation:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.operation_var = tk.StringVar(value="Ready to start")
        self.operation_label = ttk.Label(progress_grid, textvariable=self.operation_var, foreground="blue")
        self.operation_label.grid(row=0, column=1, sticky=tk.W)
        
        # Progress bar
        ttk.Label(progress_grid, text="Progress:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_grid, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=1, column=1, sticky=tk.W+tk.E, pady=(5, 0))
        progress_grid.columnconfigure(1, weight=1)
        
        # Statistics frame
        stats_frame = ttk.Frame(progress_frame)
        stats_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Statistics labels
        self.total_var = tk.StringVar(value="Total Checks: 0")
        self.processed_var = tk.StringVar(value="Processed: 0")
        self.success_var = tk.StringVar(value="✅ Successful: 0")
        self.failed_var = tk.StringVar(value="❌ Failed: 0")
        self.time_var = tk.StringVar(value="⏱️ Elapsed: 00:00")
        
        ttk.Label(stats_frame, textvariable=self.total_var).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(stats_frame, textvariable=self.processed_var).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(stats_frame, textvariable=self.success_var, foreground="green").pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(stats_frame, textvariable=self.failed_var, foreground="red").pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(stats_frame, textvariable=self.time_var).pack(side=tk.LEFT)
        
        # Login status
        login_frame = ttk.Frame(progress_frame)
        login_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.login_status_var = tk.StringVar(value="🔐 Login Status: Not required")
        self.login_status_label = ttk.Label(login_frame, textvariable=self.login_status_var, foreground="green")
        self.login_status_label.pack(side=tk.LEFT)
        
        # Action buttons section
        action_frame = ttk.LabelFrame(main_frame, text="📋 Actions", padding=10)
        action_frame.pack(fill=tk.X, pady=(0, 10))
        
        action_buttons = ttk.Frame(action_frame)
        action_buttons.pack(fill=tk.X)
        
        self.download_btn = ttk.Button(action_buttons, text="💾 Download Final CSV", command=self._on_download_final_csv, state=tk.DISABLED)
        self.download_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.streamlit_btn = ttk.Button(action_buttons, text="🔍 Open Review Tool", command=self._on_open_streamlit, state=tk.DISABLED)
        self.streamlit_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Log section
        log_frame = ttk.LabelFrame(main_frame, text="📝 Activity Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create text widget with scrollbar
        log_container = ttk.Frame(log_frame)
        log_container.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_container, height=8, wrap=tk.WORD, font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(log_container, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Status bar
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.status_var = tk.StringVar(value="Ready - Select a CSV file to begin")
        status = ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W, relief=tk.SUNKEN)
        status.pack(fill=tk.X)
        
        # Initial log message
        self._log_message("Application started. Ready to process bank statements.")

    def _log_message(self, message: str) -> None:
        """Add a timestamped message to the log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
        self.update_idletasks()

    def _update_progress(self, processed: int, total: int, success: int, failed: int) -> None:
        """Update progress indicators"""
        self.processed_checks = processed
        self.successful_checks = success
        self.failed_checks = failed
        
        if total > 0:
            progress = (processed / total) * 100
            self.progress_var.set(progress)
            self.processed_var.set(f"Processed: {processed}/{total}")
        else:
            self.progress_var.set(0)
            self.processed_var.set("Processed: 0")
        
        self.success_var.set(f"✅ Successful: {success}")
        self.failed_var.set(f"❌ Failed: {failed}")
        
        # Update elapsed time
        if self.start_time:
            elapsed = time.time() - self.start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.time_var.set(f"⏱️ Elapsed: {minutes:02d}:{seconds:02d}")

    def _update_operation(self, operation: str) -> None:
        """Update current operation display"""
        self.current_operation = operation
        self.operation_var.set(operation)
        self._log_message(f"Operation: {operation}")

    def _update_login_status(self, required: bool, message: str = "") -> None:
        """Update login status display"""
        self.login_required = required
        if required:
            self.login_status_var.set(f"🔐 Login Status: {message or 'Required - Please login in browser'}")
            self.login_status_label.config(foreground="red")
        else:
            self.login_status_var.set("🔐 Login Status: Not required")
            self.login_status_label.config(foreground="green")

    def _on_select_csv(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Select bank statement CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=os.getcwd(),  # Start from project root, not samples folder
        )
        if file_path:
            self.selected_file_path = file_path
            filename = os.path.basename(file_path)
            self.file_label_var.set(filename)
            self.status_var.set(f"Selected: {filename} - Ready to process")
            self.process_btn.config(state=tk.NORMAL)
            self._log_message(f"Selected file: {filename}")
            self._log_message("File ready for processing. Click 'Start Processing' to begin.")

    def _on_process(self) -> None:
        if not self.selected_file_path:
            messagebox.showwarning("No file", "Please select a CSV file first.")
            return

        if not self.selected_file_path.lower().endswith(".csv"):
            messagebox.showerror("Invalid file", "Only CSV files are supported.")
            return

        # Reset progress tracking
        self.total_checks = 0
        self.processed_checks = 0
        self.successful_checks = 0
        self.failed_checks = 0
        self.start_time = time.time()
        
        # Update UI
        self.status_var.set("Processing... Please wait")
        self.process_btn.config(state=tk.DISABLED)
        self.select_btn.config(state=tk.DISABLED)
        self._update_progress(0, 0, 0, 0)
        self._update_operation("Starting file processing...")
        self._log_message("Starting processing workflow...")

        threading.Thread(target=self._parse_in_background, daemon=True).start()

    def _parse_in_background(self) -> None:
        try:
            self.after(0, lambda: self._update_operation("Parsing bank statement..."))
            self.after(0, lambda: self._log_message("Reading and parsing CSV file..."))
            
            checks = parse_statement(self.selected_file_path)
            self.parsed_checks = checks
            self.total_checks = len(checks)
            
            # Update UI on main thread
            self.after(0, self._update_results)
            self.after(0, lambda: self._update_progress(0, self.total_checks, 0, 0))
            
            # Inform about export file (now in out/ directory)
            base_name = os.path.basename(self.selected_file_path).replace(".csv", "_parsed.csv")
            export_path = os.path.join("out", base_name)
            self.after(0, lambda: self._log_message(f"Successfully parsed {len(checks)} checks from statement"))
            self.after(0, lambda: self._log_message(f"Parsed data saved to: {export_path}"))

            # Auto-start image fetching using numeric min/max from parsed checks
            numbers = []
            for chk in self.parsed_checks:
                try:
                    num = int(''.join([c for c in str(chk.check_number) if c.isdigit()]))
                    numbers.append(num)
                except Exception:
                    continue

            if numbers:
                start_check = min(numbers)
                end_check = max(numbers)
                self.after(0, lambda: self._update_operation(f"Starting image fetch for checks {start_check}-{end_check}..."))
                self.after(0, lambda: self._log_message(f"Will fetch images for check range: {start_check} to {end_check}"))
                self.after(0, lambda: self._update_login_status(True, "Login required for image fetching"))
                threading.Thread(
                    target=lambda: self._run_fetch_images(start_check, end_check, export_path),
                    daemon=True,
                ).start()
            else:
                self.after(0, lambda: self._log_message("No valid check numbers found - skipping image fetch"))
                self.after(0, self._reset_controls)
                
        except Exception as e:
            self.after(0, lambda err=e: self._log_message(f"ERROR: {str(err)}"))
            self.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
        finally:
            self.after(0, self._reset_controls)

    def _update_results(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        for chk in self.parsed_checks:
            date_str = chk.date.strftime("%Y-%m-%d") if getattr(chk, "date", None) else ""
            amount_str = f"{chk.amount:.2f}" if chk.amount is not None else ""
            self.tree.insert("", tk.END, values=(chk.check_number, date_str, amount_str))

        self.status_var.set(f"Loaded {len(self.parsed_checks)} checks")

    def _reset_controls(self) -> None:
        self.process_btn.config(state=tk.NORMAL)
        self.select_btn.config(state=tk.NORMAL)
        if not self.parsed_checks:
            self.status_var.set("Ready - Select a CSV file to begin")
            self.download_btn.config(state=tk.DISABLED)
            self.streamlit_btn.config(state=tk.DISABLED)
            self._update_operation("Ready to start")
            self._update_login_status(False)

    def _run_fetch_images(self, start_check: int, end_check: int, parsed_csv_path: str) -> None:
        try:
            self.after(0, lambda: self._update_operation("Fetching check images from bank website..."))
            self.after(0, lambda: self._log_message("Opening browser for bank login..."))
            self.after(0, lambda: self._log_message("IMPORTANT: Please complete login and 2FA in the browser window"))
            
            # Calculate expected total checks
            expected_total = end_check - start_check + 1
            self.after(0, lambda: self._update_progress(0, expected_total, 0, 0))
            
            fetch_images_main(start_check=start_check, end_check=end_check, parsed_csv_path=parsed_csv_path)
            
            # Update final progress
            self.after(0, lambda: self._update_progress(expected_total, expected_total, expected_total, 0))
            self.after(0, lambda: self._update_operation("Image fetching completed successfully!"))
            self.after(0, lambda: self._update_login_status(False))
            self.after(0, lambda: self._log_message("Image fetching completed successfully"))
            
            # Prompt to save a final CSV copy and also place a copy in base out/
            def save_final_copy():
                from tkinter import filedialog
                try:
                    base_dir = os.getcwd()
                    out_dir = os.path.join(base_dir, 'out')
                    os.makedirs(out_dir, exist_ok=True)
                    import shutil
                    auto_out_path = os.path.join(
                        out_dir,
                        os.path.basename(parsed_csv_path).replace("_parsed.csv", "_final.csv"),
                    )
                    shutil.copyfile(parsed_csv_path, auto_out_path)
                    self.final_csv_path = auto_out_path
                    self.after(0, lambda: self._log_message(f"Final CSV automatically saved to: {auto_out_path}"))
                except Exception as ex:
                    self.after(0, lambda: self._log_message(f"Warning: Could not auto-save final CSV: {ex}"))
                
                # Ensure out directory exists
                out_dir = os.path.join(os.getcwd(), 'out')
                os.makedirs(out_dir, exist_ok=True)
                
                out_path = filedialog.asksaveasfilename(
                    title="Save Final CSV",
                    defaultextension=".csv",
                    filetypes=[("CSV files", "*.csv")],
                    initialdir=out_dir,  # Start from out/ folder, not samples
                    initialfile=os.path.basename(parsed_csv_path).replace("_parsed.csv", "_final.csv"),
                )
                if out_path:
                    try:
                        import shutil
                        shutil.copyfile(parsed_csv_path, out_path)
                        self.after(0, lambda: self._log_message(f"Final CSV saved to: {out_path}"))
                        messagebox.showinfo("Saved", f"Final CSV saved to\n{out_path}\n\nAlso copied to base out/ folder.")
                    except Exception as ex:
                        messagebox.showerror("Save Failed", str(ex))
                        self.after(0, lambda: self._log_message(f"ERROR: Failed to save final CSV: {ex}"))
            
            self.after(0, save_final_copy)
            # Enable action buttons after processing
            self.after(0, lambda: self.download_btn.config(state=tk.NORMAL))
            self.after(0, lambda: self.streamlit_btn.config(state=tk.NORMAL))
            self.after(0, lambda: self.status_var.set("Processing completed successfully!"))
            
        except Exception as e:
            self.after(0, lambda err=e: self._log_message(f"ERROR during image fetching: {str(err)}"))
            self.after(0, lambda err=e: messagebox.showerror("Error fetching images", str(err)))
            self.after(0, lambda: self._update_login_status(False))
        finally:
            self.after(0, lambda: self.status_var.set("Ready"))

    def _on_download_final_csv(self) -> None:
        if not self.final_csv_path or not os.path.exists(self.final_csv_path):
            messagebox.showwarning("No final CSV", "No final CSV available. Please process a file first.")
            return
        
        # Ensure out directory exists
        out_dir = os.path.join(os.getcwd(), 'out')
        os.makedirs(out_dir, exist_ok=True)
        
        out_path = filedialog.asksaveasfilename(
            title="Save Final CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialdir=out_dir,  # Start from out/ folder, not samples
            initialfile=os.path.basename(self.final_csv_path),
        )
        if out_path:
            try:
                import shutil
                shutil.copyfile(self.final_csv_path, out_path)
                messagebox.showinfo("Downloaded", f"Final CSV saved to\n{out_path}")
            except Exception as ex:
                messagebox.showerror("Download Failed", str(ex))

    def _on_open_streamlit(self) -> None:
        if not self.final_csv_path or not os.path.exists(self.final_csv_path):
            messagebox.showwarning("No final CSV", "No final CSV available. Please process a file first.")
            return
        
        try:
            import subprocess
            import sys
            import shutil
            from datetime import datetime
            
            # Get the absolute path to the reviewer.py file
            reviewer_path = os.path.join(os.getcwd(), "src", "reviewer.py")
            if not os.path.exists(reviewer_path):
                messagebox.showerror("Streamlit Error", f"Reviewer file not found at: {reviewer_path}")
                return
            
            # Prepare log file
            base_dir = os.getcwd()
            out_dir = os.path.join(base_dir, 'out')
            os.makedirs(out_dir, exist_ok=True)
            log_path = os.path.join(out_dir, 'streamlit_launch.log')
            log_file = open(log_path, 'a', encoding='utf-8')
            log_file.write(f"\n=== Launch attempt {datetime.now().isoformat()} ===\n")

            # Resolve venv python explicitly (prefer venv over current interpreter)
            if os.name == 'nt':
                venv_python = os.path.join(base_dir, 'venv', 'Scripts', 'python.exe')
                venv_streamlit_exe = os.path.join(base_dir, 'venv', 'Scripts', 'streamlit.exe')
            else:
                venv_python = os.path.join(base_dir, 'venv', 'bin', 'python')
                venv_streamlit_exe = os.path.join(base_dir, 'venv', 'bin', 'streamlit')

            python_cmd = venv_python if os.path.exists(venv_python) else sys.executable
            log_file.write(f"Using python: {python_cmd}\n")

            # Ensure streamlit is installed in the chosen interpreter (ideally venv)
            try:
                precheck = subprocess.run([python_cmd, '-c', 'import streamlit; print(streamlit.__version__)'],
                                          cwd=base_dir, capture_output=True, text=True)
                if precheck.returncode != 0:
                    log_file.write("Streamlit not available, installing into environment...\n")
                    install = subprocess.run([python_cmd, '-m', 'pip', 'install', 'streamlit==1.38.0'],
                                             cwd=base_dir, stdout=log_file, stderr=log_file, text=True)
                    log_file.write(f"pip exit code: {install.returncode}\n")
            except Exception as pip_ex:
                log_file.write(f"pip install failed: {pip_ex}\n")

            # Build possible commands (module, absolute exe in venv, PATH)
            candidates = []
            candidates.append([
                python_cmd, "-m", "streamlit", "run",
                reviewer_path,
                "--server.headless", "false",
                "--", "--csv-path", self.final_csv_path,
            ])

            if os.path.exists(venv_streamlit_exe):
                candidates.append([
                    venv_streamlit_exe, "run", reviewer_path,
                    "--server.headless", "false",
                    "--", "--csv-path", self.final_csv_path,
                ])

            if shutil.which("streamlit"):
                candidates.append([
                    "streamlit", "run", reviewer_path,
                    "--server.headless", "false",
                    "--", "--csv-path", self.final_csv_path,
                ])

            last_error = None
            for cmd in candidates:
                try:
                    log_file.write(f"Trying: {' '.join(cmd)}\n")
                    subprocess.Popen(
                        cmd,
                        cwd=base_dir,
                        stdout=log_file,
                        stderr=log_file,
                        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0,
                    )
                    messagebox.showinfo(
                        "Streamlit",
                        f"Opening Streamlit review for:\n{self.final_csv_path}\n\nIf it doesn't open, check log:\n{log_path}"
                    )
                    return
                except Exception as ex_inner:
                    last_error = ex_inner
                    log_file.write(f"Failed: {ex_inner}\n")

            # If all attempts failed
            raise last_error if last_error else RuntimeError("Failed to launch Streamlit with all methods")
        except Exception as ex:
            messagebox.showerror("Streamlit Error", f"Failed to open Streamlit: {str(ex)}")


def main() -> None:
    app = DesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()


