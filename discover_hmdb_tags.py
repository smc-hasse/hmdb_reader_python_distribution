import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


CHUNK_SIZE = 4 * 1024 * 1024
RECORD_STARTS = (b"<metabolite", b"<compound")


def local_tag_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag.rsplit(":", 1)[-1]


def iter_records(xml_path: Path):
    pending = b""
    with xml_path.open("rb") as xml_file:
        while chunk := xml_file.read(CHUNK_SIZE):
            pending += chunk
            while True:
                starts = [pending.find(marker) for marker in RECORD_STARTS]
                starts = [position for position in starts if position >= 0]
                if not starts:
                    pending = pending[-32:]
                    break

                record_start = min(starts)
                tag_end = pending.find(b">", record_start)
                if tag_end < 0:
                    pending = pending[record_start:]
                    break

                tag_name = pending[record_start + 1:tag_end].split(None, 1)[0].lower()
                if tag_name not in (b"metabolite", b"compound"):
                    pending = pending[tag_end + 1:]
                    continue

                closing = b"</" + tag_name + b">"
                record_close = pending.find(closing, tag_end + 1)
                if record_close < 0:
                    pending = pending[record_start:]
                    break

                record_end = record_close + len(closing)
                yield pending[record_start:record_end]
                pending = pending[record_end:]


def leaf_paths_for_record(record: bytes) -> set[str]:
    root = ET.fromstring(record)
    paths: set[str] = set()

    def visit(element: ET.Element, parent_path: str) -> None:
        tag_name = local_tag_name(element.tag).lower()
        current_path = f"{parent_path}->{tag_name}"
        if len(element) == 0:
            text = " ".join("".join(element.itertext()).split())
            if text:
                paths.add(current_path)
            return
        for child in element:
            visit(child, current_path)

    visit(root, "hmdb")
    return paths


def discover_tags(input_path: Path, output_path: Path) -> int:
    tags: set[str] = set()
    records = 0

    for record in iter_records(input_path):
        records += 1
        tags.update(leaf_paths_for_record(record))

    with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
        for tag in sorted(tags):
            output_file.write(f"{tag}\n")

    print(f"records_scanned={records}")
    print(f"tags_found={len(tags)}")
    print(f"output={output_path}")
    return len(tags)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover and sort HMDB XML tag paths."
    )
    parser.add_argument("input", type=Path, help="Path to hmdb_metabolites.xml")
    parser.add_argument("output", type=Path, help="Output tag-list text file")
    args = parser.parse_args()
    discover_tags(args.input, args.output)


if __name__ == "__main__":
    main()
