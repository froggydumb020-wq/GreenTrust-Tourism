"""
GreenTrust Phase 1 — Document Processor (FastAPI)
Extracts text, metadata, and structured JSON from PDF/DOCX/PNG/JPG.
"""
import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import fitz  # PyMuPDF
import pytesseract
from docx import Document as DocxDocument
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

app = FastAPI(title="GreenTrust Processor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|"
    r"\d{1,2}[/-]\d{4})\b",
    re.IGNORECASE,
)
MEASUREMENT_PATTERN = re.compile(
    r"(?<![\w.])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(KL|kL|kl|m³|m3|MWh|kWh|Wh|kW|MW|W|liters?|litres?|L|milliliters?|mL|"
    r"cubic\s+(?:meters?|metres?)|tonnes?|tons?|kg|g|mg|%|percent|°C|°F|C|F|V|A)\b",
    re.IGNORECASE,
)
MONEY_PATTERN = re.compile(
    r"(?<!\w)(?P<currency>₹|₽|€|£|\$|USD|EUR|GBP|INR|AED|AUD|CAD)\s*"
    r"(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)|"
    r"(?<!\w)(?P<amount_after>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*"
    r"(?P<currency_after>USD|EUR|GBP|INR|AED|AUD|CAD|rupees?|dollars?|euros?|pounds?)\b",
    re.IGNORECASE,
)
KEY_VALUE_PATTERN = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /()#&._-]{1,48}?)\s*(?::|=|\s[-–—]\s|\t+)\s*(.+?)\s*$")
NOISE_LINE_PATTERN = re.compile(r"^(?:[\W_]|[-_=*.]){3,}$")
ENERGY_TERMS = {"energy", "electricity", "power", "solar", "kwh", "consumption", "generator", "grid", "renewable", "meter"}
WATER_TERMS = {"water", "rainwater", "harvesting", "wastewater", "sewage", "irrigation", "pool", "consumption", "m³", "liters", "meter"}


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or NOISE_LINE_PATTERN.fullmatch(line):
            continue
        line = re.sub(r"\s*([|¦])\s*", " | ", line)
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def detect_dates(text: str) -> List[str]:
    return list(dict.fromkeys(match.group(0).strip() for match in DATE_PATTERN.finditer(text)))[:25]


def detect_measurements(text: str) -> List[str]:
    return list(dict.fromkeys(f"{m.group(1)} {m.group(2)}" for m in MEASUREMENT_PATTERN.finditer(text)))[:30]


def detect_money(text: str) -> List[str]:
    amounts = []
    for match in MONEY_PATTERN.finditer(text):
        if match.group("currency"):
            amounts.append(f"{match.group('currency')} {match.group('amount')}")
        else:
            amounts.append(f"{match.group('amount_after')} {match.group('currency_after')}")
    return list(dict.fromkeys(amounts))[:30]


def normalize_key(label: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower()).strip("_")
    return key


def detect_key_values(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in text.split("\n"):
        match = KEY_VALUE_PATTERN.match(line)
        if not match:
            continue
        key = normalize_key(match.group(1))
        value = match.group(2).strip(" |-")
        if key and value and len(key) >= 2 and len(value) <= 240:
            fields[key] = value
    return fields


def find_relevant_terms(text: str, terms: set) -> List[str]:
    lowered = text.lower()
    found = [term for term in terms if re.search(rf"(?<!\\w){re.escape(term.lower())}(?!\\w)", lowered)]
    return sorted(set(found))


def extract_pdf(buf: bytes) -> Dict:
    doc = fitz.open(stream=buf, filetype="pdf")
    pages_text = []
    ocr_used = False
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages_text.append(text)
        else:
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_text = pytesseract.image_to_string(img)
            pages_text.append(ocr_text)
            ocr_used = True
    page_count = doc.page_count
    doc.close()
    return {
        "text": "\n".join(pages_text),
        "page_count": page_count,
        "method": "PDF OCR fallback (Tesseract)" if ocr_used else "PDF text extraction (PyMuPDF)",
    }


def extract_docx(buf: bytes) -> Dict:
    doc = DocxDocument(io.BytesIO(buf))
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return {
        "text": "\n".join(parts),
        "page_count": max(1, len(parts) // 45 + 1),
        "method": "DOCX paragraph & table extraction",
    }


def extract_image(buf: bytes) -> Dict:
    img = Image.open(io.BytesIO(buf))
    text = pytesseract.image_to_string(img)
    return {"text": text, "page_count": 1, "method": "Tesseract OCR"}


def build_structured_data(file_name: str, file_type: str, text: str, metadata: Dict) -> Dict:
    meaningful_lines = [line.strip() for line in text.split("\n") if line.strip() and not NOISE_LINE_PATTERN.fullmatch(line.strip())]
    summary = " ".join(meaningful_lines)[:320].strip()
    key_excerpts = [line for line in meaningful_lines if len(line) > 20][:8]
    lowered = text.lower()
    relevant = find_relevant_terms(lowered, ENERGY_TERMS | WATER_TERMS)
    return {
        "document_information": {"file_name": file_name, "file_type": file_type},
        "summary": summary,
        "extracted_text": text,
        "key_excerpts": key_excerpts,
        "relevant_detected_terms": relevant,
        "detected_dates": detect_dates(text),
        "detected_measurements": detect_measurements(text),
        "monetary_amounts": detect_money(text),
        "key_value_fields": detect_key_values(text),
        "metadata": metadata,
    }


@app.post("/process/document")
async def process_document(file: UploadFile = File(...), document_id: str = Form(None), file_type: str = Form(None)):
    buf = await file.read()
    ftype = (file_type or Path(file.filename or "").suffix.lstrip(".")).lower()

    try:
        if ftype == "pdf":
            extraction = extract_pdf(buf)
        elif ftype == "docx":
            extraction = extract_docx(buf)
        elif ftype in ("png", "jpg", "jpeg"):
            extraction = extract_image(buf)
            ftype = "jpg" if ftype == "jpeg" else ftype
        else:
            return JSONResponse(status_code=400, content={"error": f"Unsupported file type: {ftype}"})
    except Exception as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    cleaned = clean_text(extraction["text"])
    lines = [l for l in cleaned.split("\n") if l.strip()]
    words = cleaned.split()

    metadata = {
        "file_type": ftype,
        "page_count": extraction["page_count"],
        "word_count": len(words),
        "line_count": len(lines),
        "detected_dates": detect_dates(cleaned),
        "detected_measurements": detect_measurements(cleaned),
        "monetary_amounts": detect_money(cleaned),
        "key_value_fields": detect_key_values(cleaned),
        "extraction_method": extraction["method"],
        "processed_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    structured = build_structured_data(file.filename or "document", ftype, cleaned, metadata)
    sha256 = hashlib.sha256(buf).hexdigest()

    return {
        "document_id": document_id,
        "extracted_text": cleaned,
        "structured_data": structured,
        "metadata": metadata,
        "confidence": 0.92 if "OCR" not in extraction["method"] else 0.78,
        "sha256": sha256,
        "extraction_method": extraction["method"],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "greentrust-processor"}
