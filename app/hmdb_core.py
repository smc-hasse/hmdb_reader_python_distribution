import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from .normalize_hmdb import normalize_hmdb


CHUNK_SIZE = 4 * 1024 * 1024
RECORD_STARTS = ("<metabolite", "<compound")
DOCUMENT_ROOT = "hmdb"


def local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag.rsplit(":", 1)[-1]


def iter_records(xml_path: Path):
    """Yield one metabolite/compound XML record at a time without building the full DOM."""
    pending = b""
    with xml_path.open("rb") as xml_file:
        while chunk := xml_file.read(CHUNK_SIZE):
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


def parse_input(text: str):
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    if not rows:
        return "column", []

    nonempty_counts = [sum(bool(cell.strip()) for cell in row) for row in rows]
    orientation = "column" if len(rows) > 1 and max(nonempty_counts) <= 1 else "row"
    return orientation, rows


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def values_for_record(record: bytes, requested_tags: list[str]):
    root = ET.fromstring(record)
    values_by_path = {tag: [] for tag in requested_tags}
    accessions: list[str] = []

    def visit(element: ET.Element, parent_path: str) -> None:
        tag_name = local_name(element.tag).lower()
        path = f"{parent_path}->{tag_name}"
        direct_text = "".join(
            text for text in element.itertext() if text is not None
        )
        text = _normalize_text(direct_text)

        if tag_name == "accession" and text:
            accessions.append(text)
        if path in values_by_path and text:
            values_by_path[path].append(text)

        for child in element:
            visit(child, path)

    visit(root, DOCUMENT_ROOT)

    primary = normalize_hmdb(accessions[0]) if accessions else ""
    aliases = {normalize_hmdb(item) for item in accessions}
    aliases.discard("")
    record_values = {tag: "\n".join(values_by_path.get(tag, [])) for tag in requested_tags}
    record_values["__aliases__"] = "|".join(sorted(aliases))
    return primary, record_values


def collect_values(xml_path: Path, ids: Iterable[str], requested_tags: list[str]) -> dict[str, dict[str, str]]:
    wanted = {item for item in ids if item}
    found: dict[str, dict[str, str]] = {}

    for record in iter_records(xml_path):
        primary, values = values_for_record(record, requested_tags)
        aliases = set(value for value in values.pop("__aliases__", "").split("|") if value)
        matches = wanted & aliases
        if not matches:
            continue

        values["hmdb"] = primary
        for accession in matches:
            found[accession] = values.copy()
        if len(found) == len(wanted):
            break

    return found


def make_output(text: str, values_by_id: dict[str, dict[str, str]], requested_tags: list[str]) -> str:
    orientation, rows = parse_input(text)
    if not rows:
        return ""

    labels = [tag.rsplit("->", 1)[-1] if "->" in tag else tag for tag in requested_tags]

    if orientation == "row":
        source = rows[0]
        normalized = [normalize_hmdb(cell) for cell in source]
        first_id = next((index for index, value in enumerate(normalized) if value), len(source))
        label_column = first_id - 1 if first_id > 0 else 0
        shift = 0 if first_id > 0 else 1
        width = max(len(source) + shift, label_column + 1)
        output = [[""] * width for _ in range(len(requested_tags) + 1)]
        output[0][label_column] = "hmdb"
        for index, accession in enumerate(normalized):
            if accession:
                output[0][index + shift] = accession
        for row_index, (tag, label) in enumerate(zip(requested_tags, labels), start=1):
            output[row_index][label_column] = label
            for index, accession in enumerate(normalized):
                if accession:
                    output[row_index][index + shift] = values_by_id.get(accession, {}).get(tag, "")
        return "\n".join("\t".join(row) for row in output)

    source_width = max(len(row) for row in rows)
    id_column = next(
        (index for row in rows for index, cell in enumerate(row) if normalize_hmdb(cell)),
        0,
    )
    output_width = max(source_width, id_column + 1) + len(requested_tags)
    header = [""] * output_width
    header[id_column] = "hmdb"
    for offset, label in enumerate(labels, start=source_width):
        header[offset] = label

    output = [header]
    for row in rows:
        result = [""] * output_width
        if id_column < len(row):
            accession = normalize_hmdb(row[id_column])
            result[id_column] = accession
            record_values = values_by_id.get(accession, {})
            for offset, tag in enumerate(requested_tags, start=source_width):
                result[offset] = record_values.get(tag, "")
        output.append(result)

    return "\n".join("\t".join(row) for row in output)
