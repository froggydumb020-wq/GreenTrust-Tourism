"""
GreenTrust Phase 1 — Document Processor (FastAPI)

Extracts text, metadata, and structured JSON from PDF/DOCX/PNG/JPG.

Returns:
1. Simple extraction fields for the frontend.
2. Rich structured JSON for later verification / AI processing.
"""

import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

import fitz  # PyMuPDF
import pytesseract
from docx import Document as DocxDocument
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="GreenTrust Processor",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# REGEX PATTERNS
# =========================================================

DATE_PATTERN = re.compile(
    r"\b("
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|"
    r"\d{4}[./-]\d{1,2}[./-]\d{1,2}"
    r"|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}"
    r"|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\s+\d{2,4}"
    r"|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\s+\d{4}"
    r"|"
    r"\d{1,2}[/-]\d{4}"
    r")\b",
    re.IGNORECASE,
)

MEASUREMENT_PATTERN = re.compile(
    r"(?<![\w.])"
    r"([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*"
    r"(KL|kL|kl|m³|m3|MWh|kWh|Wh|kW|MW|W|"
    r"liters?|litres?|L|milliliters?|mL|"
    r"cubic\s+(?:meters?|metres?)|"
    r"tonnes?|tons?|kg|g|mg|%|percent|°C|°F|C|F|V|A)"
    r"\b",
    re.IGNORECASE,
)

MONEY_PATTERN = re.compile(
    r"(?<!\w)"
    r"(?P<currency>₹|₽|€|£|\$|USD|EUR|GBP|INR|AED|AUD|CAD)"
    r"\s*"
    r"(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"|"
    r"(?<!\w)"
    r"(?P<amount_after>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"\s*"
    r"(?P<currency_after>USD|EUR|GBP|INR|AED|AUD|CAD|rupees?|dollars?|euros?|pounds?)"
    r"\b",
    re.IGNORECASE,
)

KEY_VALUE_PATTERN = re.compile(
    r"^\s*"
    r"([A-Za-z][A-Za-z0-9 /()#&._-]{1,60}?)"
    r"\s*(?::|=|\s[-–—]\s|\t+)"
    r"\s*(.+?)\s*$"
)

NOISE_LINE_PATTERN = re.compile(
    r"^(?:[\W_]|[-_=*]){3,}$"
)


# =========================================================
# RELEVANT TERMS
# =========================================================

ENERGY_TERMS = {
    "energy",
    "electricity",
    "power",
    "solar",
    "kwh",
    "consumption",
    "generator",
    "grid",
    "renewable",
    "meter",
}

WATER_TERMS = {
    "water",
    "rainwater",
    "harvesting",
    "wastewater",
    "sewage",
    "irrigation",
    "pool",
    "consumption",
    "m³",
    "liters",
    "meter",
}

SUSTAINABILITY_ENVIRONMENTAL_TERMS = {
    "sustainability",
    "sustainable",
    "environment",
    "environmental",
    "climate",
    "carbon",
    "emissions",
    "waste",
    "recycling",
    "biodiversity",
    "conservation",
    "procurement",
    "compliance",
    "governance",
    "renewable",
    "deforestation",
    "animal welfare",
    "community",
    "resource efficiency",
}

ALL_RELEVANT_TERMS = (
    ENERGY_TERMS | WATER_TERMS | SUSTAINABILITY_ENVIRONMENTAL_TERMS
)


# =========================================================
# SUSTAINABILITY TOPIC KEYWORD GROUPS
# =========================================================

SUSTAINABILITY_TOPICS: Dict[str, Set[str]] = {
    "carbon_reduction": {"carbon footprint", "carbon reduction", "reduce carbon", "carbon neutral", "net zero", "co2 reduction"},
    "climate": {"climate change", "climate action", "climate", "global warming", "greenhouse gas"},
    "emissions": {"emission", "emissions", "co2", "ghg", "greenhouse"},
    "energy_efficiency": {"energy efficiency", "energy conservation", "energy saving", "energy management", "energy performance"},
    "renewable_energy": {"renewable energy", "solar", "wind", "biomass", "geothermal", "renewable"},
    "water_conservation": {"water conservation", "water saving", "water efficiency", "water management", "reduce water"},
    "wastewater": {"wastewater", "sewage", "effluent", "water treatment"},
    "waste_management": {"waste management", "waste reduction", "waste disposal", "solid waste", "waste segregation"},
    "recycling": {"recycling", "recycle", "recycled", "reuse", "upcycle"},
    "sustainable_procurement": {"sustainable procurement", "green procurement", "responsible sourcing", "ethical sourcing", "supply chain"},
    "biodiversity": {"biodiversity", "ecosystem", "habitat", "species", "flora", "fauna"},
    "deforestation": {"deforestation", "reforestation", "afforestation", "tree planting", "forest"},
    "animal_welfare": {"animal welfare", "animal cruelty", "animal rights", "cruelty free"},
    "environmental_compliance": {"environmental compliance", "environmental law", "environmental regulation", "regulatory compliance", "legal compliance"},
    "environmental_governance": {"governance", "environmental policy", "environmental management system", "ems", "iso 14001"},
    "green_claims": {"green claim", "eco label", "eco-label", "green certification", "environmental claim"},
    "community_engagement": {"community engagement", "community", "local community", "social responsibility", "stakeholder"},
    "conservation": {"conservation", "protect", "preserve", "natural resource"},
    "resource_efficiency": {"resource efficiency", "resource management", "circular economy", "zero waste"},
}


# =========================================================
# COMMITMENT PHRASES
# =========================================================

COMMITMENT_PHRASES = [
    "we are committed to",
    "we will",
    "we aim to",
    "we seek to",
    "we promote",
    "we support",
    "we encourage",
    "we comply",
    "we strive to",
    "we intend to",
    "we pledge to",
    "we are dedicated to",
    "we are determined to",
    "we shall",
    "we are focused on",
]


# =========================================================
# DOCUMENT TYPE KEYWORDS
# =========================================================

DOC_TYPE_KEYWORDS: Dict[str, Set[str]] = {
    "environmental_policy": {"environmental policy", "environment policy", "environmental management policy"},
    "sustainability_policy": {"sustainability policy", "sustainable policy", "sustainability commitment", "sustainability statement"},
    "sustainability_report": {"sustainability report", "sustainability assessment", "environmental report", "esg report", "sustainability disclosure"},
    "waste_evidence": {"waste collection", "waste receipt", "waste record", "waste disposal", "waste management record"},
    "water_evidence": {"water bill", "water consumption", "water meter", "water statement", "water usage"},
    "energy_evidence": {"electricity bill", "energy bill", "energy consumption", "power bill", "electricity statement"},
    "bill_or_invoice": {"invoice", "bill", "receipt", "statement", "amount due", "total amount", "payment"},
}

def clean_text(raw: str) -> str:
    """Normalize extracted text while preserving useful content."""

    if not raw:
        return ""

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)

    lines = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()

        if not line:
            continue

        if NOISE_LINE_PATTERN.fullmatch(line):
            continue

        # Normalize table separators.
        line = re.sub(r"\s*([|¦])\s*", " | ", line)
        lines.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# =========================================================
# DATE EXTRACTION
# =========================================================

def detect_dates(text: str) -> List[str]:
    """Return unique dates found in the text."""

    return list(
        dict.fromkeys(
            match.group(0).strip()
            for match in DATE_PATTERN.finditer(text)
        )
    )[:25]


# =========================================================
# MEASUREMENT EXTRACTION
# =========================================================

def detect_measurements(text: str) -> List[str]:
    """Return simple value + unit measurements."""

    return list(
        dict.fromkeys(
            f"{match.group(1)} {match.group(2)}"
            for match in MEASUREMENT_PATTERN.finditer(text)
        )
    )[:30]


def detect_measurement_objects(text: str) -> List[Dict]:
    """Extract measurements as structured objects."""

    results = []

    for match in MEASUREMENT_PATTERN.finditer(text):
        value_text = match.group(1)
        unit = match.group(2)

        try:
            value = float(value_text.replace(",", ""))

            if value.is_integer():
                value = int(value)
        except ValueError:
            value = value_text

        # Look backwards for a possible label.
        preceding = text[max(0, match.start() - 100):match.start()]

        label_match = re.search(
            r"([A-Za-z][A-Za-z0-9 /()#&._-]{2,60})\s*:\s*$",
            preceding,
        )

        label = (
            label_match.group(1).strip()
            if label_match
            else None
        )

        item = {
            "value": value,
            "unit": unit,
        }

        if label:
            item["label"] = label

        results.append(item)

    return deduplicate_measurements(results)[:30]


def deduplicate_measurements(
    measurements: List[Dict],
) -> List[Dict]:
    """Remove duplicate value/unit pairs while preserving useful labels."""

    priority_labels = {
        "sanctioned load",
        "previous reading",
        "current reading",
        "energy consumed",
        "peak demand",
        "power factor",
        "average daily usage",
        "previous month",
        "current month",
    }

    result = {}

    for item in measurements:
        value = item.get("value")
        unit = item.get("unit")
        label = item.get("label", "").strip()
        key = (value, unit)

        if key not in result:
            result[key] = item
            continue

        existing = result[key]
        existing_label = (
            existing.get("label", "").strip().lower()
        )
        current_label = label.lower()

        if (
            current_label in priority_labels
            and existing_label not in priority_labels
        ):
            result[key] = item

    return list(result.values())


# =========================================================
# FINANCIAL EXTRACTION
# =========================================================

def detect_money(text: str) -> List[str]:
    """Return monetary amounts in their original text form."""

    amounts = []

    for match in MONEY_PATTERN.finditer(text):
        if match.group("currency"):
            amounts.append(
                f"{match.group('currency')} {match.group('amount')}"
            )
        else:
            amounts.append(
                f"{match.group('amount_after')} "
                f"{match.group('currency_after')}"
            )

    return list(dict.fromkeys(amounts))[:30]


def extract_financials(text: str) -> List[Dict]:
    """
    Extract monetary values from labelled lines.

    Example:
        1. Energy Consumption Charges
        Amount : Rs. 50,000

    becomes:
        {
            "amount": 50000,
            "currency": "INR",
            "label": "Energy Consumption Charges"
        }
    """

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    financials = []

    money_pattern = re.compile(
        r"^(.*?)\s*:\s*(?:Rs\.?|₹|INR)\s*"
        r"([\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    ignored_labels = {"amount"}
    current_section = None

    for line in lines:
        # Detect numbered section.
        numbered = re.match(r"^\d+\.\s*(.+)$", line)

        if numbered:
            current_section = numbered.group(1).strip()
            continue

        match = money_pattern.match(line)

        if not match:
            continue

        label = match.group(1).strip()
        amount_text = match.group(2).replace(",", "")

        try:
            amount = float(amount_text)
        except ValueError:
            continue

        if label.lower() in ignored_labels and current_section:
            final_label = current_section
        else:
            final_label = label

        financials.append(
            {
                "amount": amount,
                "currency": "INR",
                "label": final_label,
            }
        )

    return financials


# =========================================================
# KEY-VALUE EXTRACTION
# =========================================================

def normalize_key(label: str) -> str:
    """Convert a human-readable label into a normalized key."""

    key = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        label.strip().lower(),
    )

    return key.strip("_")


def detect_key_values(text: str) -> Dict[str, str]:
    """Extract simple key-value fields from labelled lines."""

    fields: Dict[str, str] = {}

    ignored_keys = {
        "amount",
        "consumption",
        "demand",
        "previous_month",
        "current_month",
        "note",
    }

    for line in text.split("\n"):
        match = KEY_VALUE_PATTERN.match(line)

        if not match:
            continue

        key = normalize_key(match.group(1))
        value = match.group(2).strip(" |-")

        if not key or not value:
            continue

        if len(key) < 2 or len(value) > 240:
            continue

        if key in ignored_keys:
            continue

        # Do not overwrite an existing value.
        if key not in fields:
            fields[key] = value

    return fields


# =========================================================
# RELEVANT TERM DETECTION
# =========================================================

def find_relevant_terms(
    text: str,
    terms: Set[str],
) -> List[str]:
    """Find configured sustainability terms in the text."""

    lowered = text.lower()

    found = [
        term
        for term in terms
        if re.search(
            rf"(?<!\w){re.escape(term.lower())}(?!\w)",
            lowered,
        )
    ]

    return sorted(set(found))


# =========================================================
# DOCUMENT EXTRACTION
# =========================================================

def extract_pdf(buf: bytes) -> Dict:
    """Extract PDF text with Tesseract fallback for image-only pages."""

    doc = fitz.open(stream=buf, filetype="pdf")
    pages_text = []
    ocr_used = False

    for page in doc:
        text = page.get_text("text")

        if text.strip():
            pages_text.append(text)
            continue

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
        "method": (
            "PDF OCR fallback (Tesseract)"
            if ocr_used
            else "PDF text extraction (PyMuPDF)"
        ),
    }


def extract_docx(buf: bytes) -> Dict:
    """Extract DOCX paragraphs and table contents."""

    doc = DocxDocument(io.BytesIO(buf))
    parts = []

    # Paragraphs.
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)

    # Tables.
    for table in doc.tables:
        for row in table.rows:
            cells = [
                cell.text.strip()
                for cell in row.cells
                if cell.text.strip()
            ]

            if cells:
                parts.append(" | ".join(cells))

    return {
        "text": "\n".join(parts),
        "page_count": max(1, len(parts) // 45 + 1),
        "method": "DOCX paragraph & table extraction",
    }


def extract_image(buf: bytes) -> Dict:
    """Extract text from PNG/JPG/JPEG using Tesseract OCR."""

    img = Image.open(io.BytesIO(buf))
    text = pytesseract.image_to_string(img)

    return {
        "text": text,
        "page_count": 1,
        "method": "Tesseract OCR",
    }


# =========================================================
# DOCUMENT TYPE CLASSIFICATION
# =========================================================

def classify_document_type(text: str, file_name: str) -> str:
    """Classify document using deterministic keyword matching."""

    lowered = text.lower()
    fn_lower = file_name.lower()

    # Check filename first for strong signals
    if "environmental policy" in fn_lower or "env_policy" in fn_lower:
        return "environmental_policy"
    if "sustainability policy" in fn_lower or "sustain_policy" in fn_lower:
        return "sustainability_policy"
    if "sustainability report" in fn_lower or "esg_report" in fn_lower:
        return "sustainability_report"

    # Score each type by keyword hits
    scores: Dict[str, int] = {}
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = sum(
            1 for kw in keywords if kw in lowered
        )
        if score > 0:
            scores[doc_type] = score

    if not scores:
        return "general_evidence"

    # Policy/report types take priority over bill_or_invoice
    # when they score equally or higher
    policy_types = {
        "environmental_policy",
        "sustainability_policy",
        "sustainability_report",
    }

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    # If a policy type has at least 1 hit and bill also has hits,
    # prefer policy when policy score >= bill score
    if best_type in policy_types:
        return best_type

    # Check if any policy type also matches
    for pt in policy_types:
        if pt in scores and scores[pt] >= best_score:
            return pt

    return best_type


# =========================================================
# TITLE DETECTION
# =========================================================

NUMBERED_HEADING_PATTERN = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*)[.)]\s+(.+)$"
)


def detect_title(text: str, file_name: str) -> str:
    """Detect document title from first-page headings or filename."""

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
        and not NOISE_LINE_PATTERN.fullmatch(line.strip())
    ]

    if not lines:
        # Fall back to filename without extension
        return Path(file_name).stem.replace("_", " ").title()

    # Strategy 1: First meaningful line that looks like a title
    # (short, not a sentence, possibly title-case or uppercase)
    for line in lines[:10]:
        stripped = line.strip()

        # Skip lines that are clearly body text (too long or ends with period)
        if len(stripped) > 120 or stripped.endswith("."):
            continue

        # Skip numbered headings for title (we capture those as sections)
        if NUMBERED_HEADING_PATTERN.match(stripped):
            continue

        # Uppercase or title-case short line = likely title
        if len(stripped) >= 5 and (
            stripped.isupper()
            or stripped.istitle()
            or sum(1 for c in stripped if c.isupper()) > len(stripped) * 0.3
        ):
            return stripped

    # Strategy 2: First non-numbered meaningful line
    for line in lines[:5]:
        stripped = line.strip()
        if not NUMBERED_HEADING_PATTERN.match(stripped) and len(stripped) >= 5:
            if len(stripped) <= 120:
                return stripped

    # Strategy 3: Filename
    return Path(file_name).stem.replace("_", " ").title()


# =========================================================
# ORGANIZATION DETECTION
# =========================================================

ORG_NAME_PATTERN = re.compile(
    r"\b(?:hotel|resort|villa|lodge|guest\s*house|homestay|boutique|eco\s*lodge|company|organization|organisation|property|establishment)\s+([A-Z][A-Za-z0-9\s&'.,-]{2,60})"
)


def detect_organization(text: str, key_values: Dict[str, str]) -> str:
    """Extract organization/hotel/company name when clearly present."""

    # Check key-value fields first
    org_keys = [
        "hotel_name", "property_name", "organization",
        "organisation", "company", "company_name",
        "customer_name", "establishment", "name",
    ]
    for k in org_keys:
        if k in key_values and key_values[k]:
            return key_values[k]

    # Search in text
    m = ORG_NAME_PATTERN.search(text)
    if m:
        return m.group(1).strip()

    # Look for ALL-CAPS lines that look like organization names
    for line in text.split("\n"):
        line = line.strip()
        if len(line) > 5 and line.isupper() and any(
            w in line.lower()
            for w in ["hotel", "resort", "villa", "lodge", "company", "group"]
        ):
            return line

    return ""


# =========================================================
# SUSTAINABILITY TOPICS DETECTION
# =========================================================

def detect_sustainability_topics(text: str) -> List[str]:
    """Detect sustainability topics using rule-based keyword groups."""

    lowered = text.lower()
    found = []

    for topic, keywords in SUSTAINABILITY_TOPICS.items():
        for kw in keywords:
            if kw in lowered:
                found.append(topic)
                break

    return sorted(set(found))


# =========================================================
# POLICY SECTIONS DETECTION
# =========================================================

# Keywords that indicate a sustainability-related heading
SECTION_KEYWORDS = {
    "carbon", "emission", "energy", "water", "waste", "recycling",
    "procurement", "biodiversity", "deforestation", "forest",
    "compliance", "governance", "engagement", "community",
    "conservation", "resource", "climate", "environment",
    "sustainability", "sustainable", "policy", "introduction",
    "objective", "commitment", "scope", "purpose", "responsibility",
    "monitoring", "reporting", "review", "animal welfare",
}


def detect_policy_sections(text: str) -> List[Dict]:
    """Detect meaningful headings/sections in policy documents."""

    lines = text.split("\n")
    sections = []
    seen = set()

    for line in lines:
        stripped = line.strip()

        if not stripped or len(stripped) < 3:
            continue

        if NOISE_LINE_PATTERN.fullmatch(stripped):
            continue

        matched = False
        section_title = None
        section_number = None

        # 1. Numbered headings: "1. Title", "2.1 Title", "3) Title"
        m = NUMBERED_HEADING_PATTERN.match(stripped)
        if m:
            section_title = m.group(1).strip()
            section_number = re.match(
                r"\s*(\d+(?:\.\d+)*)", stripped
            ).group(1)
            matched = True

        # 2. Uppercase headings (not too long, not a full sentence)
        if not matched:
            if (
                len(stripped) >= 4
                and len(stripped) <= 80
                and stripped.isupper()
                and not stripped.endswith(".")
                and sum(1 for c in stripped if c.isalpha()) > 2
            ):
                section_title = stripped
                matched = True

        # 3. Short standalone headings that look like titles
        # (title-case, short, no ending period, contains section keyword)
        if not matched:
            if (
                len(stripped) >= 4
                and len(stripped) <= 80
                and not stripped.endswith(".")
                and not stripped.endswith(",")
                and stripped.istitle()
            ):
                lowered = stripped.lower()
                if any(kw in lowered for kw in SECTION_KEYWORDS):
                    section_title = stripped
                    matched = True

        # 4. Heading followed by content pattern (Title:\n body text)
        # Already handled by uppercase/title-case checks above

        if matched and section_title:
            # Filter out body sentences disguised as headings
            word_count = len(section_title.split())
            if word_count > 15:
                continue

            # Deduplicate by normalized title
            norm = section_title.lower().strip()
            if norm in seen:
                continue
            seen.add(norm)

            entry: Dict[str, str] = {"heading": section_title}
            if section_number:
                entry["number"] = section_number

            sections.append(entry)

    return sections[:30]


# =========================================================
# KEY COMMITMENTS EXTRACTION
# =========================================================

def extract_key_commitments(text: str) -> List[str]:
    """Extract sentences containing commitment phrases."""

    # Split into sentences (handle common sentence boundaries)
    # Preserve the original text as-is
    sentences = re.split(
        r"(?<=[.!?])\s+(?=[A-Z])",
        text,
    )

    # Also check across newlines — join lines first for multi-line sentences
    # But also check line-by-line for commitment phrases
    all_sentences = list(sentences)

    # Also check joined lines for commitments that span newlines
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # Check if this line starts a commitment
        lowered_line = line.lower()
        if any(line.lower().startswith(p) for p in COMMITMENT_PHRASES):
            # Collect the full sentence — may span multiple lines
            full = line
            j = i + 1
            while j < len(lines) and not lines[j].strip().endswith("."):
                full += " " + lines[j].strip()
                j += 1
                if j - i > 5:  # safety limit
                    break
            if j < len(lines) and lines[j].strip():
                full += " " + lines[j].strip()
            all_sentences.append(full)
            i = j + 1
            continue
        i += 1

    commitments = []
    seen = set()

    for sentence in all_sentences:
        stripped = sentence.strip()
        if not stripped or len(stripped) < 10:
            continue

        lowered = stripped.lower()

        for phrase in COMMITMENT_PHRASES:
            if phrase in lowered:
                # Clean up whitespace
                cleaned_sentence = " ".join(stripped.split())
                # Cap length
                if len(cleaned_sentence) > 300:
                    cleaned_sentence = cleaned_sentence[:297] + "..."

                norm = cleaned_sentence.lower().strip()
                if norm not in seen:
                    seen.add(norm)
                    commitments.append(cleaned_sentence)
                break

    return commitments[:20]


# =========================================================
# DOCUMENT-TYPE-AWARE SUMMARY
# =========================================================

def build_summary(
    key_values: Dict[str, str],
    measurements: List[Dict],
    financials: List[Dict],
    document_type: str,
    organization: str,
    policy_sections: List[Dict],
    sustainability_topics: List[str],
    key_commitments: List[str],
) -> str:
    """Build a short human-readable summary, document-type aware."""

    # --- Bill/invoice summary (existing behavior) ---
    bill_types = {"bill_or_invoice", "water_evidence", "energy_evidence"}

    if document_type in bill_types:
        customer = (
            key_values.get("customer_name")
            or key_values.get("hotel_name")
            or key_values.get("property_name")
        )
        billing_period = key_values.get("billing_period")
        energy = (
            key_values.get("energy_consumed")
            or key_values.get("total_consumption")
        )

        total_due = None
        for item in financials:
            label = (item.get("label") or "").lower()
            if "total amount due" in label:
                currency = item.get("currency", "INR")
                total_due = f"{currency} {item['amount']:,.2f}"
                break

        parts = []
        if customer:
            parts.append(f"Bill for {customer}")
        if billing_period:
            parts.append(f"covering {billing_period}")
        if energy:
            parts.append(f"with energy consumption of {energy}")
        if total_due:
            parts.append(f"and total amount due of {total_due}")
        if parts:
            return " ".join(parts) + "."

        return "Document containing extracted billing information."

    # --- Policy/report summary (new behavior) ---
    parts = []

    type_labels = {
        "environmental_policy": "Environmental Policy",
        "sustainability_policy": "Sustainability Policy",
        "sustainability_report": "Sustainability Report",
        "waste_evidence": "Waste Evidence",
        "general_evidence": "Evidence Document",
    }
    type_label = type_labels.get(document_type, "Document")
    parts.append(type_label)

    if organization:
        parts.append(f"from {organization}")

    section_count = len(policy_sections)
    if section_count > 0:
        parts.append(f"with {section_count} policy section{'s' if section_count != 1 else ''}")

    topic_count = len(sustainability_topics)
    if topic_count > 0:
        topics_str = ", ".join(sustainability_topics[:5])
        if topic_count > 5:
            topics_str += f" and {topic_count - 5} more"
        parts.append(f"covering topics: {topics_str}")

    commit_count = len(key_commitments)
    if commit_count > 0:
        parts.append(f"and {commit_count} key commitment{'s' if commit_count != 1 else ''}")

    if len(parts) > 1:
        return " ".join(parts) + "."

    return f"{type_label} document containing extracted sustainability evidence."


# =========================================================
# STRUCTURED JSON
# =========================================================

def build_structured_data(
    file_name: str,
    file_type: str,
    text: str,
    metadata: Dict,
) -> Dict:
    """Build the rich structured representation returned by the processor."""

    key_values = detect_key_values(text)
    measurements = detect_measurement_objects(text)
    financials = extract_financials(text)
    dates = detect_dates(text)

    meaningful_lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
        and not NOISE_LINE_PATTERN.fullmatch(line.strip())
    ]

    key_excerpts = [
        line
        for line in meaningful_lines
        if len(line) > 20
    ][:8]

    # --- New: document type, title, organization ---
    document_type = classify_document_type(text, file_name)
    title = detect_title(text, file_name)
    organization = detect_organization(text, key_values)

    # --- New: sustainability topics, policy sections, commitments ---
    sustainability_topics = detect_sustainability_topics(text)
    policy_sections = detect_policy_sections(text)
    key_commitments = extract_key_commitments(text)

    # --- Expanded relevant terms (energy + water + sustainability) ---
    relevant = find_relevant_terms(
        text,
        ALL_RELEVANT_TERMS,
    )

    redundant_keys = {
        "consumption",
        "demand",
        "amount",
        "previous_month",
        "current_month",
    }

    key_values = {
        key: value
        for key, value in key_values.items()
        if key not in redundant_keys
    }

    # --- Document-type-aware summary ---
    summary = build_summary(
        key_values,
        measurements,
        financials,
        document_type,
        organization,
        policy_sections,
        sustainability_topics,
        key_commitments,
    )

    return {
        "document": {
            "file_name": file_name,
            "file_type": file_type,
            "page_count": metadata["page_count"],
        },
        "document_type": document_type,
        "title": title,
        "organization": organization,
        "summary": summary,
        "key_data": key_values,
        "measurements": measurements,
        "financials": financials,
        "dates": dates,
        "relevant_terms": relevant,
        "sustainability_topics": sustainability_topics,
        "policy_sections": policy_sections,
        "key_commitments": key_commitments,
        "key_excerpts": key_excerpts,
        "metadata": {
            "word_count": metadata["word_count"],
            "line_count": metadata["line_count"],
            "extraction_method": metadata["extraction_method"],
            "processed_timestamp": metadata["processed_timestamp"],
        },
    }


# =========================================================
# DOCUMENT PROCESSING ENDPOINT
# =========================================================

@app.post("/process/document")
async def process_document(
    file: UploadFile = File(...),
    document_id: str = Form(None),
    file_type: str = Form(None),
):
    """Extract, clean, structure, and hash an uploaded document."""

    # -----------------------------------------------------
    # 1. Read uploaded file
    # -----------------------------------------------------

    buf = await file.read()

    # -----------------------------------------------------
    # 2. Determine file type
    # -----------------------------------------------------

    ftype = (
        file_type
        or Path(file.filename or "").suffix.lstrip(".")
    ).lower()

    # -----------------------------------------------------
    # 3. Extract document content
    # -----------------------------------------------------

    try:
        if ftype == "pdf":
            extraction = extract_pdf(buf)

        elif ftype == "docx":
            extraction = extract_docx(buf)

        elif ftype in {"png", "jpg", "jpeg"}:
            extraction = extract_image(buf)

            if ftype == "jpeg":
                ftype = "jpg"

        else:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"Unsupported file type: {ftype}",
                },
            )

    except Exception as exc:
        return JSONResponse(
            status_code=422,
            content={"error": str(exc)},
        )

    # -----------------------------------------------------
    # 4. Clean extracted text
    # -----------------------------------------------------

    cleaned = clean_text(extraction["text"])

    # -----------------------------------------------------
    # 5. Basic counts
    # -----------------------------------------------------

    lines = [
        line
        for line in cleaned.split("\n")
        if line.strip()
    ]
    words = cleaned.split()

    # -----------------------------------------------------
    # 6. Simple extraction fields for frontend
    # -----------------------------------------------------

    detected_dates = detect_dates(cleaned)
    detected_measurements = detect_measurements(cleaned)
    monetary_amounts = detect_money(cleaned)
    key_value_fields = detect_key_values(cleaned)

    relevant_detected_terms = find_relevant_terms(
        cleaned,
        ALL_RELEVANT_TERMS,
    )

    # -----------------------------------------------------
    # 7. Technical metadata
    # -----------------------------------------------------

    metadata = {
        "file_type": ftype,
        "page_count": extraction["page_count"],
        "word_count": len(words),
        "line_count": len(lines),
        "detected_dates": detected_dates,
        "detected_measurements": detected_measurements,
        "monetary_amounts": monetary_amounts,
        "key_value_fields": key_value_fields,
        "relevant_detected_terms": relevant_detected_terms,
        "extraction_method": extraction["method"],
        "processed_timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    # -----------------------------------------------------
    # 8. Rich structured JSON
    # -----------------------------------------------------

    structured = build_structured_data(
        file.filename or "document",
        ftype,
        cleaned,
        metadata,
    )

    # -----------------------------------------------------
    # 9. SHA-256 file hash
    # -----------------------------------------------------

    sha256 = hashlib.sha256(buf).hexdigest()

    # -----------------------------------------------------
    # 10. Final response
    # -----------------------------------------------------

    return {
        "document_id": document_id,
        "extracted_text": cleaned,
        "structured_data": structured,
        "metadata": metadata,
        "confidence": (
            0.92
            if "OCR" not in extraction["method"]
            else 0.78
        ),
        "sha256": sha256,
        "extraction_method": extraction["method"],
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
async def health():
    """Health check for the processor service."""

    return {
        "status": "ok",
        "service": "greentrust-processor",
    }
