import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import xml.etree.ElementTree as ET
import re


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_XML = BASE_DIR / "hmdb_metabolites.xml"
DEFAULT_TAGS = BASE_DIR / "hmdb_tag_results.txt"
DEFAULT_TAGS_FULL = BASE_DIR / "hmdb_tag_results_all.txt"


HMDB_PATTERN = re.compile(r"^HMDB(\d+)$", re.IGNORECASE)
CHUNK_SIZE = 4 * 1024 * 1024
RECORD_STARTS = ("<metabolite", "<compound")
DOCUMENT_ROOT = "hmdb"


def normalize_hmdb(value: str) -> str:
    match = HMDB_PATTERN.fullmatch((value or "").strip())
    if match is None:
        return ""
    digits = match.group(1)
    if len(digits) > 7:
        return ""
    return f"HMDB{digits.zfill(7)}"


def parse_input(text: str):
    if not text:
        return "column", []
    rows = [line.split("\t") for line in text.splitlines()]
    if not rows:
        return "column", []
    nonempty_counts = [sum(bool(cell.strip()) for cell in row) for row in rows]
    orientation = "column" if len(rows) > 1 and max(nonempty_counts) <= 1 else "row"
    return orientation, rows


def local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag.rsplit(":", 1)[-1]


def iter_records(xml_path: Path):
    pending = b""
    with xml_path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            pending += chunk
            while True:
                positions = [pending.find(marker.encode("utf-8")) for marker in RECORD_STARTS]
                positions = [pos for pos in positions if pos >= 0]
                if not positions:
                    pending = pending[-32:]
                    break

                record_start = min(positions)
                tag_end = pending.find(b">", record_start)
                if tag_end < 0:
                    pending = pending[record_start:]
                    break

                tag_fragment = pending[record_start + 1:tag_end].split(None, 1)[0].decode("utf-8", errors="ignore").lower()
                if tag_fragment not in {"metabolite", "compound"}:
                    pending = pending[tag_end + 1:]
                    continue

                closing = f"</{tag_fragment}>".encode("utf-8")
                record_close = pending.find(closing, tag_end + 1)
                if record_close < 0:
                    pending = pending[record_start:]
                    break

                record_end = record_close + len(closing)
                yield pending[record_start:record_end]
                pending = pending[record_end:]


def find_values_for_record(record: bytes, requested_tags: list[str]):
    root = ET.fromstring(record)
    values_by_path = {tag: [] for tag in requested_tags}
    accessions: list[str] = []

    def walk(element: ET.Element, parent_path: str) -> None:
        tag_name = local_name(element.tag).lower()
        path = f"{parent_path}->{tag_name}"
        text = " ".join("".join(element.itertext()).split())
        if tag_name == "accession" and text:
            accessions.append(text)
        if path in values_by_path and text:
            values_by_path[path].append(text)
        for child in element:
            walk(child, path)

    walk(root, DOCUMENT_ROOT)

    primary = normalize_hmdb(accessions[0]) if accessions else ""
    aliases = {normalize_hmdb(item) for item in accessions}
    aliases.discard("")
    record_values = {tag: "\n".join(values_by_path.get(tag, [])) for tag in requested_tags}
    record_values["__aliases__"] = "|".join(sorted(aliases))
    return primary, record_values


def collect_values(xml_path: Path, ids, requested_tags: list[str]) -> dict[str, dict[str, str]]:
    wanted = {item for item in ids if item}
    found: dict[str, dict[str, str]] = {}

    for record in iter_records(xml_path):
        primary, values = find_values_for_record(record, requested_tags)
        aliases = {value for value in values.pop("__aliases__", "").split("|") if value}
        matches = wanted & aliases
        if not matches:
            continue
        values["hmdb"] = primary
        for accession in matches:
            found[accession] = values.copy()
        if len(found) == len(wanted):
            break
    return found


def make_output(text: str, values_by_id: dict[str, dict[str, str]], requested_tags: list[str], include_full_paths: bool = False) -> str:
    orientation, rows = parse_input(text)
    if not rows:
        return ""

    labels = [tag if include_full_paths else tag.rsplit("->", 1)[-1] if "->" in tag else tag for tag in requested_tags]

    if orientation == "row":
        source = rows[0]
        width = len(source) + 1
        output = [[""] * width for _ in range(len(requested_tags) + 1)]
        output[0][0] = "hmdb"
        for index, cell in enumerate(source, start=1):
            output[0][index] = normalize_hmdb(cell)
        for row_index, (tag, label) in enumerate(zip(requested_tags, labels), start=1):
            output[row_index][0] = label
            for index, cell in enumerate(source, start=1):
                accession = normalize_hmdb(cell)
                if accession:
                    output[row_index][index] = values_by_id.get(accession, {}).get(tag, "")
        return "\n".join("\t".join(row) for row in output)

    source_width = max(len(row) for row in rows)
    output_width = source_width + len(requested_tags)
    header = [""] * output_width
    header[0] = "hmdb"
    for offset, label in enumerate(labels, start=source_width):
        header[offset] = label

    output = [header]
    for row in rows:
        result = [""] * output_width
        valid_id = ""
        for cell in row:
            candidate = normalize_hmdb(cell)
            if candidate:
                valid_id = candidate
                break
        result[0] = valid_id
        if valid_id:
            record_values = values_by_id.get(valid_id, {})
            for offset, tag in enumerate(requested_tags, start=source_width):
                result[offset] = record_values.get(tag, "")
        output.append(result)

    return "\n".join("\t".join(row) for row in output)


class HmdbApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("HMDB tag retriever")
        self.root.geometry("760x620")
        self.root.minsize(620, 480)

        self.clipboard_text = ""
        self.output_text = ""
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_values_by_id: dict[str, dict[str, str]] = {}
        self.last_selected_tags: list[str] = []
        self.last_input_text = ""
        self.xml_path = tk.StringVar(value=str(DEFAULT_XML))
        self.status = tk.StringVar(value="Copy HMDB IDs in Excel, then fetch them here.")
        self.selected_count = tk.StringVar(value="0 tags selected")
        self.use_full_tags = tk.BooleanVar(value=False)
        self.use_full_headers = tk.BooleanVar(value=False)

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
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tag_list.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tag_list.configure(yscrollcommand=yscroll.set)
        self.tag_list.bind("<<ListboxSelect>>", self._on_tag_selection_change)

        tag_buttons = ttk.Frame(tags_frame)
        tag_buttons.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(tag_buttons, text="Select all", command=self._select_all).pack(side="left")
        ttk.Button(tag_buttons, text="Clear", command=self._clear_selection).pack(side="left", padx=(6, 0))
        ttk.Label(tag_buttons, textvariable=self.selected_count).pack(side="right")

        options = ttk.Frame(tags_frame)
        options.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Checkbutton(options, text="Use full tag list", variable=self.use_full_tags, command=self._load_tags).pack(side="left")
        ttk.Checkbutton(options, text="Use full paths in headers", variable=self.use_full_headers, command=self._refresh_output_from_cache).pack(side="left", padx=(16, 0))

        action_row = ttk.Frame(self.root)
        action_row.grid(row=2, column=0, sticky="ew", padx=12, pady=8)
        self.retrieve_button = ttk.Button(action_row, text="Retrieve selected tags", command=self._retrieve)
        self.retrieve_button.grid(row=0, column=0, padx=(0, 6))
        self.save_button = ttk.Button(action_row, text="Save TSV...", command=self._save_output, state="disabled")
        self.save_button.grid(row=0, column=1, padx=6)
        self.copy_button = ttk.Button(action_row, text="Copy result", command=self._copy_output, state="disabled")
        self.copy_button.grid(row=0, column=2, padx=6)

        status = ttk.Label(self.root, textvariable=self.status, anchor="w", relief="sunken")
        status.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))

    def _active_tag_file(self) -> Path:
        return DEFAULT_TAGS_FULL if self.use_full_tags.get() else DEFAULT_TAGS

    def _load_tags(self) -> None:
        selected_before = [self.tag_list.get(index) for index in self.tag_list.curselection()]
        self.tag_list.delete(0, "end")
        tag_file = self._active_tag_file()
        try:
            tags: list[str] = []
            if tag_file.exists():
                for line in tag_file.read_text(encoding="utf-8-sig").splitlines():
                    cleaned = line.strip()
                    if not cleaned:
                        continue
                    tag = cleaned.lower()
                    if tag and tag not in tags:
                        tags.append(tag)
            for tag in tags:
                self.tag_list.insert("end", tag)

            for index, tag in enumerate(tags):
                if tag in selected_before:
                    self.tag_list.selection_set(index)
        except OSError as error:
            messagebox.showerror("Cannot load tags", str(error))
        self._update_selected_count()

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
        valid_ids = []
        for row in rows:
            for cell in row:
                candidate = normalize_hmdb(cell)
                if candidate:
                    valid_ids.append(candidate)
        if not valid_ids:
            self.clipboard_text = ""
            self.status.set("No valid HMDB IDs found in the clipboard.")
            messagebox.showwarning("Clipboard", "No values matching HMDB followed by up to 7 digits were found.")
            return

        self.clipboard_text = text
        self.status.set(f"Ready: {len(valid_ids)} valid HMDB ID cell(s) found in the clipboard.")

    def _select_all(self) -> None:
        self.tag_list.selection_set(0, "end")
        self._on_tag_selection_change()

    def _clear_selection(self) -> None:
        self.tag_list.selection_clear(0, "end")
        self._on_tag_selection_change()

    def _on_tag_selection_change(self, _event=None) -> None:
        self._update_selected_count()
        self.retrieve_button.configure(state="normal")
        self.save_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")

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
        self.status.set("Scanning the HMDB XML. This may take a while...")
        threading.Thread(target=self._run_scan, args=(xml_path, selected), daemon=True).start()

    def _refresh_output_from_cache(self) -> None:
        if not self.last_values_by_id or not self.last_selected_tags or not self.last_input_text:
            return
        self.output_text = make_output(
            self.last_input_text,
            self.last_values_by_id,
            self.last_selected_tags,
            include_full_paths=self.use_full_headers.get(),
        )
        self.save_button.configure(state="normal")
        self.copy_button.configure(state="normal")
        self.status.set("Updated result header format.")

    def _run_scan(self, xml_path: Path, selected: list[str]) -> None:
        try:
            _, rows = parse_input(self.clipboard_text)
            ids = []
            for row in rows:
                for cell in row:
                    candidate = normalize_hmdb(cell)
                    if candidate:
                        ids.append(candidate)
            values = collect_values(xml_path, ids, selected)
            self.last_values_by_id = values
            self.last_selected_tags = selected
            self.last_input_text = self.clipboard_text
            output = make_output(self.clipboard_text, values, selected, include_full_paths=self.use_full_headers.get())
            self.events.put(("success", (output, len(values))))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _process_events(self) -> None:
        try:
            event, payload = self.events.get_nowait()
        except queue.Empty:
            self.root.after(100, self._process_events)
            return

        self.retrieve_button.configure(state="normal")
        if event == "success":
            self.output_text, found = payload
            self.save_button.configure(state="normal")
            self.copy_button.configure(state="normal")
            self.status.set(f"Finished: {found} record(s) found. Choose Save TSV or Copy result.")
        else:
            messagebox.showerror("Retrieval failed", str(payload))
            self.status.set("Retrieval failed.")
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
                self.status.set(f"Saved: {path}")
            except OSError as error:
                messagebox.showerror("Save failed", str(error))

    def _copy_output(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.output_text)
        self.root.update()
        self.status.set("Result copied to the clipboard and ready to paste into Excel.")


def main() -> None:
    root = tk.Tk()
    HmdbApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
