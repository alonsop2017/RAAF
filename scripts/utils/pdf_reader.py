#!/usr/bin/env python3
"""
PDF text extraction utility.
Uses pdfplumber for reliable text extraction from PDF resumes.
Falls back to OCR (easyocr) for image-based PDFs.
"""

import sys
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# Lazy loading for OCR to avoid slow startup
_easyocr_reader = None


def _get_ocr_reader():
    """Get or create the easyocr reader (lazy loading)."""
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        except ImportError:
            raise ImportError("easyocr is not installed. Run: pip install easyocr")
    return _easyocr_reader


def extract_text_pdfplumber(pdf_path: Path) -> str:
    """Extract text from PDF using pdfplumber."""
    if pdfplumber is None:
        raise ImportError("pdfplumber is not installed. Run: pip install pdfplumber")

    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    return "\n\n".join(text_parts)


def extract_text_pymupdf(pdf_path: Path) -> str:
    """Extract text from PDF using PyMuPDF (fitz)."""
    if fitz is None:
        raise ImportError("PyMuPDF is not installed. Run: pip install pymupdf")

    text_parts = []
    doc = fitz.open(pdf_path)
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()

    return "\n\n".join(text_parts)


def extract_text_ocr(pdf_path: Path) -> str:
    """
    Extract text from image-based PDF using OCR (easyocr).
    Converts each PDF page to an image and runs OCR.
    """
    if fitz is None:
        raise ImportError("PyMuPDF is required for OCR. Run: pip install pymupdf")

    reader = _get_ocr_reader()

    text_parts = []
    doc = fitz.open(pdf_path)

    for page_num, page in enumerate(doc):
        # Convert page to image (higher DPI for better OCR)
        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for ~144 DPI
        pix = page.get_pixmap(matrix=mat)

        # Convert to PIL Image for easyocr
        img_data = pix.tobytes("png")

        # Run OCR
        import io
        results = reader.readtext(img_data)

        # Extract text from results
        page_text = "\n".join([text for _, text, _ in results])
        if page_text.strip():
            text_parts.append(page_text)

    doc.close()

    return "\n\n".join(text_parts)


def extract_text(pdf_path: Path | str, method: Optional[str] = None, use_ocr_fallback: bool = True) -> str:
    """
    Extract text from a PDF file.

    Args:
        pdf_path: Path to the PDF file
        method: Extraction method ('pdfplumber', 'pymupdf', 'ocr', or None for auto)
        use_ocr_fallback: If True, automatically use OCR when text extraction returns empty

    Returns:
        Extracted text as a string

    Raises:
        FileNotFoundError: If the PDF file doesn't exist
        ImportError: If required library is not installed
        ValueError: If the file is not a valid PDF
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"File is not a PDF: {pdf_path}")

    # If OCR is explicitly requested
    if method == "ocr":
        return extract_text_ocr(pdf_path)

    # Auto-select method based on available libraries
    if method is None:
        if pdfplumber is not None:
            method = "pdfplumber"
        elif fitz is not None:
            method = "pymupdf"
        else:
            raise ImportError(
                "No PDF library available. Install one of:\n"
                "  pip install pdfplumber\n"
                "  pip install pymupdf"
            )

    # Try standard text extraction
    if method == "pdfplumber":
        text = extract_text_pdfplumber(pdf_path)
    elif method == "pymupdf":
        text = extract_text_pymupdf(pdf_path)
    else:
        raise ValueError(f"Unknown extraction method: {method}")

    # Fall back to OCR if text extraction returned empty/minimal content
    if use_ocr_fallback and len(text.strip()) < 50:
        try:
            print(f"    Text extraction returned minimal content, trying OCR...")
            ocr_text = extract_text_ocr(pdf_path)
            if len(ocr_text.strip()) > len(text.strip()):
                return ocr_text
        except ImportError as e:
            print(f"    OCR fallback unavailable: {e}")
        except Exception as e:
            print(f"    OCR fallback failed: {e}")

    return text


def extract_text_with_metadata(pdf_path: Path | str) -> dict:
    """
    Extract text and metadata from a PDF file.

    Returns:
        Dictionary with 'text', 'pages', 'metadata' keys
    """
    pdf_path = Path(pdf_path)

    result = {
        "text": "",
        "pages": 0,
        "metadata": {},
        "source_file": pdf_path.name
    }

    if pdfplumber is not None:
        with pdfplumber.open(pdf_path) as pdf:
            result["pages"] = len(pdf.pages)
            result["metadata"] = pdf.metadata or {}

            text_parts = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            result["text"] = "\n\n".join(text_parts)

    elif fitz is not None:
        doc = fitz.open(pdf_path)
        result["pages"] = len(doc)
        result["metadata"] = doc.metadata or {}

        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        result["text"] = "\n\n".join(text_parts)

    else:
        raise ImportError("No PDF library available")

    return result


def clean_extracted_text(text: str) -> str:
    """
    Clean up extracted text by removing excess whitespace and fixing common issues.

    Args:
        text: Raw extracted text

    Returns:
        Cleaned text
    """
    import re

    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)

    # Replace multiple newlines with double newline
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Fix common OCR issues
    text = text.replace('ﬁ', 'fi')
    text = text.replace('ﬂ', 'fl')
    text = text.replace('ﬀ', 'ff')

    # Remove leading/trailing whitespace from lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    return text.strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_reader.py <pdf_file>")
        sys.exit(1)

    pdf_file = Path(sys.argv[1])
    try:
        text = extract_text(pdf_file)
        text = clean_extracted_text(text)
        print(text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
