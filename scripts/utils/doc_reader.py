#!/usr/bin/env python3
"""
.doc-extension text extraction utility.

In production, files arriving with a `.doc` extension turn out to be a mix
of three actual formats:
  - genuine Word 97-2003 binary (OLE2/CFBF) documents
  - RTF documents saved with a `.doc` extension (job-board exports)
  - plain text saved with a `.doc` extension (e.g. Monster.com email exports)

python-docx only reads the OOXML .docx zip format and raises on all three,
and a naive UTF-8 decode of the raw bytes silently produces garbled or
empty text for the genuine binary case. This sniffs the actual format from
the file's magic bytes and dispatches accordingly.
"""

import subprocess
import sys
from pathlib import Path

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_RTF_MAGIC = b"{\\rtf"


def _extract_ole2(doc_path: Path) -> str:
    """Genuine Word 97-2003 binary document, via antiword."""
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


def _extract_rtf(doc_path: Path) -> str:
    """RTF content saved with a .doc extension."""
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        raise ImportError("striprtf is not installed. Run: pip install striprtf")

    raw = doc_path.read_text(encoding="utf-8", errors="ignore")
    return rtf_to_text(raw)


def _extract_plain_text(doc_path: Path) -> str:
    """Plain text saved with a .doc extension (e.g. job-board email exports)."""
    return doc_path.read_text(encoding="utf-8", errors="ignore")


def extract_text(doc_path: Path | str) -> str:
    """
    Extract text from a .doc-extension file, auto-detecting the real
    underlying format (binary OLE2, RTF, or plain text) from its magic bytes.

    Args:
        doc_path: Path to the .doc file

    Returns:
        Extracted text as a string

    Raises:
        FileNotFoundError: If the file doesn't exist
        RuntimeError: If antiword is required but not installed
        ImportError: If striprtf is required but not installed
        ValueError: If extraction fails
    """
    doc_path = Path(doc_path)

    if not doc_path.exists():
        raise FileNotFoundError(f"DOC file not found: {doc_path}")

    with open(doc_path, "rb") as f:
        head = f.read(8)

    if head.startswith(_OLE2_MAGIC):
        return _extract_ole2(doc_path)
    elif head.startswith(_RTF_MAGIC):
        return _extract_rtf(doc_path)
    else:
        return _extract_plain_text(doc_path)


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
