import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List

from seed_checks import parse_statement, CheckTransaction
from fetch_images import main as fetch_images_main


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Check Payee Automation - Desktop")
        self.minsize(800, 500)

        self.selected_file_path: str | None = None
        self.parsed_checks: List[CheckTransaction] = []

        self._build_ui()

    def _build_ui(self) -> None:
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill=tk.X)

        self.select_btn = ttk.Button(top_frame, text="Select CSV...", command=self._on_select_csv)
        self.select_btn.pack(side=tk.LEFT)

        self.file_label_var = tk.StringVar(value="No file selected")
        self.file_label = ttk.Label(top_frame, textvariable=self.file_label_var)
        self.file_label.pack(side=tk.LEFT, padx=10)

        self.process_btn = ttk.Button(top_frame, text="Process", command=self._on_process)
        self.process_btn.pack(side=tk.RIGHT)

        # Table
        columns = ("check_number", "date", "amount")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("check_number", text="Check Number")
        self.tree.heading("date", text="Date")
        self.tree.heading("amount", text="Amount")
        self.tree.column("check_number", width=200, anchor=tk.W)
        self.tree.column("date", width=150, anchor=tk.W)
        self.tree.column("amount", width=120, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status = ttk.Label(self, textvariable=self.status_var, anchor=tk.W)
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def _on_select_csv(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Select bank statement CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if file_path:
            self.selected_file_path = file_path
            self.file_label_var.set(file_path)
            self.status_var.set("Selected file. Click Process to parse.")

    def _on_process(self) -> None:
        if not self.selected_file_path:
            messagebox.showwarning("No file", "Please select a CSV file first.")
            return

        if not self.selected_file_path.lower().endswith(".csv"):
            messagebox.showerror("Invalid file", "Only CSV files are supported.")
            return

        # Run parsing in separate thread so UI remains responsive
        self.status_var.set("Processing...")
        self.process_btn.config(state=tk.DISABLED)
        self.select_btn.config(state=tk.DISABLED)

        threading.Thread(target=self._parse_in_background, daemon=True).start()

    def _parse_in_background(self) -> None:
        try:
            checks = parse_statement(self.selected_file_path)
            self.parsed_checks = checks
            # Update UI on main thread
            self.after(0, self._update_results)
            # Inform about export file
            export_path = self.selected_file_path.replace(".csv", "_parsed.csv")
            self.after(0, lambda: messagebox.showinfo("Completed", f"Parsed {len(checks)} checks.\nSaved: {export_path}"))

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
                self.after(0, lambda: self.status_var.set(f"Fetching images {start_check}-{end_check}..."))
                threading.Thread(
                    target=lambda: self._run_fetch_images(start_check, end_check, export_path),
                    daemon=True,
                ).start()
        except Exception as e:
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
            self.status_var.set("Ready")

    def _run_fetch_images(self, start_check: int, end_check: int, parsed_csv_path: str) -> None:
        try:
            fetch_images_main(start_check=start_check, end_check=end_check, parsed_csv_path=parsed_csv_path)
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
                except Exception:
                    pass
                out_path = filedialog.asksaveasfilename(
                    title="Save Final CSV",
                    defaultextension=".csv",
                    filetypes=[("CSV files", "*.csv")],
                    initialfile=os.path.basename(parsed_csv_path).replace("_parsed.csv", "_final.csv"),
                )
                if out_path:
                    try:
                        import shutil
                        shutil.copyfile(parsed_csv_path, out_path)
                        messagebox.showinfo("Saved", f"Final CSV saved to\n{out_path}\n\nAlso copied to base out/ folder.")
                    except Exception as ex:
                        messagebox.showerror("Save Failed", str(ex))
            self.after(0, save_final_copy)
        except Exception as e:
            self.after(0, lambda err=e: messagebox.showerror("Error fetching images", str(err)))
        finally:
            self.after(0, lambda: self.status_var.set("Ready"))


def main() -> None:
    app = DesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()


