import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .hmdb_core import collect_values, make_output, parse_input
from .normalize_hmdb import normalize_hmdb


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_XML = BASE_DIR / "hmdb_metabolites.xml"
DEFAULT_TAGS = BASE_DIR / "hmdb_tag_results.txt"


class HmdbApp:
    def __init__(self, root) -> None:
        self.root = root
        self.root.title("HMDB tag retriever")
        self.root.geometry("760x620")
        self.root.minsize(620, 480)

        self.clipboard_text = ""
        self.output_text = ""
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        self.xml_path = tk.StringVar(value=str(DEFAULT_XML))
        self.status_text = tk.StringVar(value="Copy HMDB IDs in Excel, then fetch them here.")
        self.selected_count = tk.StringVar(value="0 tags selected")
        self.progress_value = tk.DoubleVar(value=0)

        self._build_ui()
        self._load_tags()
        self.root.after(100, self._process_events)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        source = ttk.LabelFrame(self.root, text="Source")
        source.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        source.columnconfigure(1, weight=1)

        ttk.Label(source, text="HMDB XML:").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(source, textvariable=self.xml_path).grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        ttk.Button(source, text="Browse...", command=self._choose_xml).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(source, text="Fetch IDs from clipboard", command=self._fetch_clipboard).grid(
            row=1, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w"
        )

        tags_frame = ttk.LabelFrame(self.root, text="Tags to retrieve")
        tags_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        tags_frame.columnconfigure(0, weight=1)
        tags_frame.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(tags_frame)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tag_list = tk.Listbox(list_frame, selectmode=tk.EXTENDED, exportselection=False)
        self.tag_list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tag_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tag_list.configure(yscrollcommand=scrollbar.set)
        self.tag_list.bind("<<ListboxSelect>>", self._update_selected_count)

        tag_buttons = ttk.Frame(tags_frame)
        tag_buttons.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(tag_buttons, text="Select all", command=self._select_all).pack(side="left")
        ttk.Button(tag_buttons, text="Clear", command=self._clear_selection).pack(side="left", padx=(6, 0))
        ttk.Label(tag_buttons, textvariable=self.selected_count).pack(side="right")

        actions = ttk.Frame(self.root)
        actions.grid(row=2, column=0, sticky="ew", padx=12, pady=8)
        self.retrieve_button = ttk.Button(actions, text="Retrieve selected tags", command=self._retrieve)
        self.retrieve_button.grid(row=0, column=0, padx=(0, 6))
        self.save_button = ttk.Button(actions, text="Save TSV...", command=self._save_output, state="disabled")
        self.save_button.grid(row=0, column=1, padx=6)
        self.copy_button = ttk.Button(actions, text="Copy result", command=self._copy_output, state="disabled")
        self.copy_button.grid(row=0, column=2, padx=6)
        self.progress = ttk.Progressbar(actions, variable=self.progress_value, mode="indeterminate")
        self.progress.grid(row=0, column=3, sticky="ew", padx=(12, 0))

        status = ttk.Label(self.root, textvariable=self.status_text, anchor="w", relief="sunken")
        status.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))

    def _load_tags(self) -> None:
        try:
            tags = []
            if DEFAULT_TAGS.exists():
                for line in DEFAULT_TAGS.read_text(encoding="utf-8-sig").splitlines():
                    parts = line.split("\t", 1)
                    tag = parts[1].strip().lower() if len(parts) == 2 else parts[0].strip().lower()
                    if tag and tag not in tags:
                        tags.append(tag)
            for tag in tags:
                self.tag_list.insert("end", tag)
        except OSError as error:
            messagebox.showerror("Cannot load tags", str(error))

    def _choose_xml(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose HMDB XML file",
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
            initialdir=str(BASE_DIR),
        )
        if path:
            self.xml_path.set(path)

    def _fetch_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except Exception:
            messagebox.showwarning("Clipboard", "The clipboard does not contain readable text.")
            return

        _, rows = parse_input(text)
        valid_ids = [normalize_hmdb(cell) for row in rows for cell in row if normalize_hmdb(cell)]
        if not valid_ids:
            self.clipboard_text = ""
            self.status_text.set("No valid HMDB IDs found in the clipboard.")
            messagebox.showwarning("Clipboard", "No values matching HMDB followed by up to 7 digits were found.")
            return

        self.clipboard_text = text
        self.status_text.set(f"Ready: {len(valid_ids)} valid HMDB ID cell(s) found in the clipboard.")

    def _select_all(self) -> None:
        self.tag_list.selection_set(0, "end")
        self._update_selected_count()

    def _clear_selection(self) -> None:
        self.tag_list.selection_clear(0, "end")
        self._update_selected_count()

    def _update_selected_count(self, _event=None) -> None:
        count = len(self.tag_list.curselection())
        self.selected_count.set(f"{count} tag{'s' if count != 1 else ''} selected")

    def _retrieve(self) -> None:
        if not self.clipboard_text:
            messagebox.showwarning("IDs required", "Fetch HMDB IDs from the clipboard first.")
            return
        selected = [self.tag_list.get(index) for index in self.tag_list.curselection()]
        if not selected:
            messagebox.showwarning("Tags required", "Select at least one tag to retrieve.")
            return

        xml_path = Path(self.xml_path.get())
        if not xml_path.is_file():
            messagebox.showerror("XML file not found", str(xml_path))
            return

        self.retrieve_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.progress.start(10)
        self.status_text.set("Scanning the HMDB XML. This may take a while...")
        threading.Thread(target=self._retrieve_worker, args=(xml_path, selected), daemon=True).start()

    def _retrieve_worker(self, xml_path: Path, selected: list[str]) -> None:
        try:
            _, rows = parse_input(self.clipboard_text)
            ids = [normalize_hmdb(cell) for row in rows for cell in row]
            values = collect_values(xml_path, ids, selected)
            output = make_output(self.clipboard_text, values, selected)
            self.events.put(("success", (output, len(values))))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _process_events(self) -> None:
        try:
            event, payload = self.events.get_nowait()
        except queue.Empty:
            self.root.after(100, self._process_events)
            return

        self.progress.stop()
        self.retrieve_button.configure(state="normal")
        if event == "success":
            self.output_text, found = payload
            self.save_button.configure(state="normal")
            self.copy_button.configure(state="normal")
            self.status_text.set(f"Finished: {found} record(s) found. Choose Save TSV or Copy result.")
        else:
            messagebox.showerror("Retrieval failed", payload)
            self.status_text.set("Retrieval failed.")
        self.root.after(100, self._process_events)

    def _save_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save retrieved HMDB data",
            defaultextension=".tsv",
            filetypes=[("Tab-separated values", "*.tsv"), ("All files", "*.*")],
            initialdir=str(BASE_DIR),
            initialfile="hmdb_retrieved_output.tsv",
        )
        if path:
            try:
                Path(path).write_text(self.output_text, encoding="utf-8", newline="\n")
                self.status_text.set(f"Saved: {path}")
            except OSError as error:
                messagebox.showerror("Save failed", str(error))

    def _copy_output(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.output_text)
        self.root.update()
        self.status_text.set("Result copied to the clipboard and ready to paste into Excel.")


def main() -> None:
    import tkinter as tk

    root = tk.Tk()
    app = HmdbApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
