# HMDB Tag Retriever (Python, source-based)

This project is a source-only Python version of the HMDB reader. It is designed for sharing on GitHub in environments where EXE distribution is restricted or not allowed.

The app reads HMDB IDs from clipboard data, lets you select which tag fields to retrieve, scans a large HMDB XML file efficiently, and exports the result as TSV output while preserving the original table layout.

## Why this project is source-based

The HMDB XML file is very large, and a naïve full-document parse can consume excessive memory or fail. This app uses a streaming record-by-record XML scan so it can process metabolite data without loading the entire HMDB database into memory at once.

This keeps the project practical and safe for users who cannot rely on a compiled EXE build.

## Requirements

- Python 3.10 or newer
- Tkinter support (usually included with standard Windows Python installs)
- `hmdb_metabolites.xml` placed in the same folder as the project
- `hmdb_tag_results.txt` and `hmdb_tag_results_all.txt` placed in the same folder

## Download the HMDB XML file

The HMDB XML file is available from the official HMDB downloads page:

https://hmdb.ca/downloads

Use:
- Version: 5.0
- File: All Metabolites
- Date: 2021-11-17

The downloaded XML file is large. The unpacked dataset may be several GB depending on the release and extraction format.

## Install Python on Windows

Recommended option:

```powershell
winget install Python.Python.3.12
```

Then verify:

```powershell
py -3 --version
```

## Run the app

From the project folder:

```powershell
cd "C:\path\to\hmdb_reader_python_distribution"
py -3 main.py
```

Or directly:

```powershell
py -3 "C:\path\to\hmdb_reader_python_distribution\main.py"
```

## Behavior

- invalid or non-HMDB cells are treated as empty without shifting the table
- valid HMDB IDs keep their original row and column positions
- the short tag list is selected by default
- the full tag list is available via a checkbox
- short headers are selected by default
- full XML-path headers are available via a checkbox

## Output

The app can:
- fetch HMDB IDs from the clipboard
- select tags to retrieve
- scan the XML efficiently
- display extracted values in the interface
- save results as a TSV file
- copy the result back to the clipboard

## Notes

This project is intended for source distribution only. It is suitable for GitHub sharing and for users in environments where executable packaging is restricted or prohibited.

## License

This project is provided as-is for research and data extraction workflows. Please check the HMDB terms and licensing for the downloaded XML dataset before redistribution or reuse in other environments.
