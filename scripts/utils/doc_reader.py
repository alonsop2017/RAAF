#!/usr/bin/env python3
"""
Legacy .doc (Word 97-2003 binary format) text extraction utility.

python-docx only reads the OOXML .docx zip format, so legacy .doc files
were previously falling through to a raw UTF-8 decode of the binary OLE2
bytes, producing garbled or empty text. This shells out to `antiword`,
which understands the binary format directly.
"""

import subprocess
import sys
from pathlib import Path


def extract_text(doc_path: Path | str) -> str:
    """
    Extract text from a legacy .doc file via antiword.

    Args:
        doc_path: Path to the .doc file

    Returns:
        Extracted text as a string

    Raises:
        FileNotFoundError: If the file doesn't exist
        RuntimeError: If antiword is not installed
        ValueError: If antiword fails to parse the file
    """
    doc_path = Path(doc_path)

    if not doc_path.exists():
        raise FileNotFoundError(f"DOC file not found: {doc_path}")

    try:
        result = subprocess.run(
            ["antiword", str(doc_path)],
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "antiword is not installed. Install it with: apt-get install antiword"
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"antiword timed out extracting {doc_path.name}")

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore").strip()
        raise ValueError(
            f"antiword failed to extract {doc_path.name}: {stderr or 'unknown error'}"
        )

    return result.stdout.decode("utf-8", errors="ignore")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python doc_reader.py <doc_file>")
        sys.exit(1)

    doc_file = Path(sys.argv[1])
    try:
        print(extract_text(doc_file))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
