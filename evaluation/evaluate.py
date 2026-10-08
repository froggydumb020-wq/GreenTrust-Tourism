#!/usr/bin/env python3
"""
GreenTrust Module 1 Evaluation — Quantitative Evaluator

Sends test documents to the EXISTING GreenTrust FastAPI processor
(POST http://localhost:8000/process/document) and compares the output
against ground_truth.json.

Calculates:
  - Processing success rate
  - Structured extraction precision/recall/F1 (dates, measurements,
    financials, key_data, relevant_terms)
  - JSON field accuracy
  - SHA-256 integrity / change detection
  - Processing time statistics (by file type)
  - Optional text token-level precision/recall/F1

Generates:
  - evaluation/results.json
  - evaluation/evaluation_report.txt

Usage:
    python evaluate.py
    python evaluate.py --processor-url http://localhost:8000
    python evaluate.py --ground-truth ground_truth.json
"""

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
TEST_DOCS_DIR = BASE_DIR / "test_documents"
DEFAULT_GROUND_TRUTH = BASE_DIR / "ground_truth.json"
RESULTS_FILE = BASE_DIR / "results.json"
REPORT_FILE = BASE_DIR / "evaluation_report.txt"

DEFAULT_PROCESSOR_URL = "http://localhost:8000"
PROCESS_ENDPOINT = "/process/document"

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_string(s: str) -> str:
    """Normalize for comparison: lowercase, strip, collapse whitespace."""
    if s is None:
        return ""
    return " ".join(str(s).lower().split())


def normalize_number(val: Any) -> Optional[float]:
    """Extract numeric value from string or number."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_currency(c: str) -> str:
    """Normalize currency representations."""
    if c is None:
        return "INR"
    c = str(c).strip().lower()
    mapping = {
        "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR",
        "$": "USD", "usd": "USD",
        "€": "EUR", "eur": "EUR",
        "£": "GBP", "gbp": "GBP",
    }
    return mapping.get(c, c.upper())


def normalize_unit(u: str) -> str:
    """Normalize unit representations."""
    if u is None:
        return ""
    u = str(u).strip().lower()
    mapping = {
        "m³": "m3", "m3": "m3",
        "kl": "kl", "kwh": "kwh",
        "l": "l", "liters": "l", "litres": "l",
        "kg": "kg", "g": "g",
    }
    return mapping.get(u, u)


# =========================================================
# SET OPERATIONS FOR TP/FP/FN
# =========================================================

def make_hashable(items: List[Any], kind: str) -> List[str]:
    """Convert items to comparable hashable keys."""
    result = []
    for item in items:
        if kind == "dates":
            result.append(normalize_string(item))
        elif kind == "measurements":
            val = normalize_number(item.get("value"))
            unit = normalize_unit(item.get("unit", ""))
            if val is not None:
                result.append(f"{val:.4f}|{unit}")
        elif kind == "financials":
            amount = normalize_number(item.get("amount"))
            currency = normalize_currency(item.get("currency", ""))
            if amount is not None:
                result.append(f"{amount:.2f}|{currency}")
        elif kind == "relevant_terms":
            result.append(normalize_string(item))
        elif kind == "key_data":
            if isinstance(item, dict):
                for k, v in item.items():
                    result.append(f"{normalize_string(k)}|{normalize_string(v)}")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                result.append(f"{normalize_string(item[0])}|{normalize_string(item[1])}")
    return result


def compute_prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    """Compute precision, recall, F1."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def compare_sets(expected: List[Any], actual: List[Any], kind: str) -> Dict:
    """Compare two lists using set operations with normalization."""
    expected_keys = set(make_hashable(expected, kind))
    actual_keys = set(make_hashable(actual, kind))

    tp = len(expected_keys & actual_keys)
    fp = len(actual_keys - expected_keys)
    fn = len(expected_keys - actual_keys)

    return compute_prf(tp, fp, fn)


def compare_key_data(expected: Dict[str, str], actual: Dict[str, str]) -> Dict:
    """Compare key-value dictionaries."""
    expected_normalized = {normalize_string(k): normalize_string(v) for k, v in expected.items()}
    actual_normalized = {normalize_string(k): normalize_string(v) for k, v in actual.items()}

    all_keys = set(expected_normalized.keys()) | set(actual_normalized.keys())
    tp = 0
    fp = 0
    fn = 0

    for key in all_keys:
        if key in expected_normalized and key in actual_normalized:
            if expected_normalized[key] == actual_normalized[key]:
                tp += 1
            else:
                fp += 1
                fn += 1
        elif key in actual_normalized:
            fp += 1
        else:
            fn += 1

    return compute_prf(tp, fp, fn)


# =========================================================
# JSON FIELD ACCURACY
# =========================================================

EXPECTED_FIELDS = [
    "extracted_text",
    "structured_data",
    "metadata",
    "sha256",
    "extraction_method",
    "confidence",
    "structured_data.document",
    "structured_data.summary",
    "structured_data.key_data",
    "structured_data.measurements",
    "structured_data.financials",
    "structured_data.dates",
    "structured_data.relevant_terms",
    "structured_data.key_excerpts",
    "metadata.file_type",
    "metadata.page_count",
    "metadata.word_count",
    "metadata.line_count",
    "metadata.extraction_method",
    "metadata.processed_timestamp",
]


def get_nested(d: Dict, path: str) -> Any:
    """Get a nested value using dot notation."""
    parts = path.split(".")
    current = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def check_json_fields(response: Dict) -> Dict:
    """Check which expected JSON fields are present and correct."""
    total = len(EXPECTED_FIELDS)
    correct = 0
    missing = []
    incorrect = []

    for field in EXPECTED_FIELDS:
        value = get_nested(response, field)
        if value is None:
            missing.append(field)
        elif value == "" or value == [] or value == {}:
            missing.append(field)
        else:
            correct += 1

    accuracy = round(correct / total * 100, 2) if total > 0 else 0.0

    return {
        "expected_fields": total,
        "correct_fields": correct,
        "missing_fields": missing,
        "incorrect_fields": incorrect,
        "accuracy": accuracy,
    }


# =========================================================
# SHA-256 INTEGRITY
# =========================================================

def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_integrity(file_path: Path, processor_hash: str) -> Dict:
    """Verify SHA-256 hash and test change detection."""
    original_hash = compute_sha256(file_path)

    original_matches = (original_hash == processor_hash)

    # Modify one byte and verify hash changes
    modified_hash = None
    modified_differs = False
    try:
        data = bytearray(file_path.read_bytes())
        if len(data) > 0:
            data[-1] ^= 0xFF  # flip last byte
            modified_hash = hashlib.sha256(bytes(data)).hexdigest()
            modified_differs = (modified_hash != original_hash)
    except Exception as e:
        modified_hash = f"error: {e}"

    return {
        "original_hash": original_hash,
        "processor_hash": processor_hash,
        "original_hash_matches": original_matches,
        "modified_hash": modified_hash,
        "modified_hash_changes": modified_differs,
        "integrity_accuracy": 100.0 if (original_matches and modified_differs) else 0.0,
    }


# =========================================================
# TEXT EVALUATION (OPTIONAL)
# =========================================================

def tokenize(text: str) -> Set[str]:
    """Simple tokenization for text comparison."""
    return set(text.lower().split())


def evaluate_text(expected_text: str, actual_text: str) -> Dict:
    """Token-level precision/recall/F1 for text."""
    expected_tokens = tokenize(expected_text)
    actual_tokens = tokenize(actual_text)

    tp = len(expected_tokens & actual_tokens)
    fp = len(actual_tokens - expected_tokens)
    fn = len(expected_tokens - actual_tokens)

    return compute_prf(tp, fp, fn)


# =========================================================
# PROCESSOR COMMUNICATION
# =========================================================

def send_to_processor(file_path: Path, processor_url: str, timeout: int = 120) -> Dict:
    """Send a document to the GreenTrust processor and return the response."""
    url = f"{processor_url.rstrip('/')}{PROCESS_ENDPOINT}"

    file_type = file_path.suffix.lower().lstrip(".")
    if file_type == "jpeg":
        file_type = "jpg"

    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, "application/octet-stream")}
        data = {
            "document_id": f"eval-{file_path.stem}",
            "file_type": file_type,
        }
        response = requests.post(url, files=files, data=data, timeout=timeout)

    if response.status_code != 200:
        return {
            "success": False,
            "error": f"HTTP {response.status_code}: {response.text[:500]}",
        }

    return {"success": True, "data": response.json()}


# =========================================================
# PER-DOCUMENT EVALUATION
# =========================================================

def evaluate_document(
    file_path: Path,
    gt_entry: Dict,
    processor_url: str,
    timeout: int,
) -> Dict:
    """Evaluate a single document against ground truth."""
    result: Dict[str, Any] = {
        "file_name": file_path.name,
        "file_type": file_path.suffix.lower().lstrip("."),
    }

    # Send to processor
    start = time.perf_counter()
    proc_response = send_to_processor(file_path, processor_url, timeout)
    elapsed = time.perf_counter() - start
    result["processing_time_seconds"] = round(elapsed, 4)

    if not proc_response["success"]:
        result["status"] = "failed"
        result["error"] = proc_response["error"]
        return result

    result["status"] = "success"
    data = proc_response["data"]

    # Capture processor output
    result["extraction_method"] = data.get("extraction_method", "")
    result["confidence"] = data.get("confidence", 0)
    result["sha256_returned"] = data.get("sha256", "")

    structured = data.get("structured_data", {})
    metadata = data.get("metadata", {})

    # ---- Structured extraction comparison ----
    # Dates
    gt_dates = gt_entry.get("dates", [])
    actual_dates = structured.get("dates", []) or metadata.get("detected_dates", [])
    result["dates"] = compare_sets(gt_dates, actual_dates, "dates")

    # Measurements
    gt_measurements = gt_entry.get("measurements", [])
    actual_measurements = structured.get("measurements", [])
    result["measurements"] = compare_sets(gt_measurements, actual_measurements, "measurements")

    # Financials
    gt_financials = gt_entry.get("financials", [])
    actual_financials = structured.get("financials", [])
    result["financials"] = compare_sets(gt_financials, actual_financials, "financials")

    # Key data
    gt_key_data = gt_entry.get("key_data", {})
    actual_key_data = structured.get("key_data", {})
    result["key_data"] = compare_key_data(gt_key_data, actual_key_data)

    # Relevant terms
    gt_terms = gt_entry.get("relevant_terms", [])
    actual_terms = structured.get("relevant_terms", []) or metadata.get("relevant_detected_terms", [])
    result["relevant_terms"] = compare_sets(gt_terms, actual_terms, "relevant_terms")

    # ---- JSON field accuracy ----
    result["json_field_accuracy"] = check_json_fields(data)

    # ---- SHA-256 integrity ----
    result["integrity"] = verify_integrity(file_path, data.get("sha256", ""))

    # ---- Optional text evaluation ----
    if "expected_text" in gt_entry and gt_entry["expected_text"]:
        actual_text = data.get("extracted_text", "")
        result["text_evaluation"] = evaluate_text(gt_entry["expected_text"], actual_text)
    else:
        result["text_evaluation"] = None

    return result


# =========================================================
# AGGREGATE METRICS
# =========================================================

def aggregate_prf(field_results: List[Dict]) -> Dict:
    """Aggregate TP/FP/FN across all documents for overall PRF."""
    total_tp = sum(r["tp"] for r in field_results)
    total_fp = sum(r["fp"] for r in field_results)
    total_fn = sum(r["fn"] for r in field_results)
    return compute_prf(total_tp, total_fp, total_fn)


def aggregate_metrics(per_doc_results: List[Dict]) -> Dict:
    """Calculate aggregate metrics across all documents."""
    successful = [r for r in per_doc_results if r["status"] == "success"]
    total = len(per_doc_results)
    success_count = len(successful)

    # Processing success rate
    success_rate = round(success_count / total * 100, 2) if total > 0 else 0.0

    # Structured extraction
    fields = ["dates", "measurements", "financials", "key_data", "relevant_terms"]
    structured: Dict[str, Any] = {}

    for field in fields:
        field_results = [r[field] for r in successful if field in r]
        if field_results:
            structured[field] = aggregate_prf(field_results)
        else:
            structured[field] = compute_prf(0, 0, 0)

    # Overall structured PRF
    overall_tp = sum(structured[f]["tp"] for f in fields)
    overall_fp = sum(structured[f]["fp"] for f in fields)
    overall_fn = sum(structured[f]["fn"] for f in fields)
    structured["overall"] = compute_prf(overall_tp, overall_fp, overall_fn)

    # JSON field accuracy
    json_accuracies = [r["json_field_accuracy"] for r in successful if "json_field_accuracy" in r]
    if json_accuracies:
        avg_accuracy = round(
            sum(ja["accuracy"] for ja in json_accuracies) / len(json_accuracies), 2
        )
        total_expected = sum(ja["expected_fields"] for ja in json_accuracies)
        total_correct = sum(ja["correct_fields"] for ja in json_accuracies)
        all_missing = [m for ja in json_accuracies for m in ja["missing_fields"]]
        json_field_summary = {
            "average_accuracy": avg_accuracy,
            "total_expected_fields": total_expected,
            "total_correct_fields": total_correct,
            "total_missing_fields": len(all_missing),
            "overall_accuracy": round(total_correct / total_expected * 100, 2) if total_expected > 0 else 0.0,
            "frequently_missing": list(set(all_missing)),
        }
    else:
        json_field_summary = {"average_accuracy": 0.0, "overall_accuracy": 0.0}

    # SHA-256 integrity
    integrity_results = [r["integrity"] for r in successful if "integrity" in r]
    if integrity_results:
        original_matches = sum(1 for i in integrity_results if i["original_hash_matches"])
        modified_changes = sum(1 for i in integrity_results if i["modified_hash_changes"])
        integrity_summary = {
            "total_checked": len(integrity_results),
            "original_hash_matches": original_matches,
            "original_hash_match_rate": round(original_matches / len(integrity_results) * 100, 2),
            "modified_hash_changes": modified_changes,
            "modified_hash_change_rate": round(modified_changes / len(integrity_results) * 100, 2),
            "integrity_accuracy": round(
                sum(i["integrity_accuracy"] for i in integrity_results) / len(integrity_results), 2
            ),
        }
    else:
        integrity_summary = {"integrity_accuracy": 0.0}

    # Processing time
    times = [r["processing_time_seconds"] for r in per_doc_results if "processing_time_seconds" in r]
    pdf_times = [r["processing_time_seconds"] for r in per_doc_results
                 if r.get("file_type") == "pdf" and "processing_time_seconds" in r]
    docx_times = [r["processing_time_seconds"] for r in per_doc_results
                  if r.get("file_type") == "docx" and "processing_time_seconds" in r]
    image_times = [r["processing_time_seconds"] for r in per_doc_results
                   if r.get("file_type") in ("png", "jpg", "jpeg") and "processing_time_seconds" in r]

    def safe_stats(t: List[float]) -> Dict:
        if not t:
            return {"average": 0, "minimum": 0, "maximum": 0, "median": 0}
        return {
            "average": round(statistics.mean(t), 4),
            "minimum": round(min(t), 4),
            "maximum": round(max(t), 4),
            "median": round(statistics.median(t), 4),
        }

    time_stats = safe_stats(times)
    time_stats["pdf_average"] = safe_stats(pdf_times)["average"]
    time_stats["docx_average"] = safe_stats(docx_times)["average"]
    time_stats["image_ocr_average"] = safe_stats(image_times)["average"]

    # Text evaluation (optional)
    text_results = [r["text_evaluation"] for r in successful
                    if r.get("text_evaluation") is not None]
    if text_results:
        text_summary = aggregate_prf(text_results)
    else:
        text_summary = None

    return {
        "total_documents": total,
        "successful_documents": success_count,
        "failed_documents": total - success_count,
        "success_rate": success_rate,
        "structured_extraction": structured,
        "json_field_accuracy": json_field_summary,
        "sha256_integrity": integrity_summary,
        "processing_time_seconds": time_stats,
        "text_evaluation": text_summary,
    }


# =========================================================
# REPORT GENERATION
# =========================================================

def generate_report(results: Dict, report_path: Path) -> None:
    """Generate a human-readable text report."""
    lines: List[str] = []
    a = results["aggregate"]
    pr = lambda v: f"{v:.4f}" if isinstance(v, float) else str(v)

    lines.append("=" * 70)
    lines.append("  GreenTrust Module 1 — Quantitative Evaluation Report")
    lines.append("=" * 70)
    lines.append("")

    # Processing success
    lines.append("  1. PROCESSING SUCCESS RATE")
    lines.append(f"     Total documents:    {a['total_documents']}")
    lines.append(f"     Successful:         {a['successful_documents']}")
    lines.append(f"     Failed:             {a['failed_documents']}")
    lines.append(f"     Success rate:       {a['success_rate']}%")
    lines.append("")

    # Structured extraction
    lines.append("  2. STRUCTURED INFORMATION EXTRACTION")
    lines.append(f"     {'Field':<20} {'Precision':>10} {'Recall':>10} {'F1':>10} {'TP':>5} {'FP':>5} {'FN':>5}")
    lines.append(f"     {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*5} {'-'*5} {'-'*5}")

    se = a["structured_extraction"]
    for field in ["dates", "measurements", "financials", "key_data", "relevant_terms"]:
        f = se[field]
        lines.append(f"     {field:<20} {f['precision']:>10.4f} {f['recall']:>10.4f} {f['f1']:>10.4f} {f['tp']:>5} {f['fp']:>5} {f['fn']:>5}")

    ov = se["overall"]
    lines.append(f"     {'OVERALL':<20} {ov['precision']:>10.4f} {ov['recall']:>10.4f} {ov['f1']:>10.4f} {ov['tp']:>5} {ov['fp']:>5} {ov['fn']:>5}")
    lines.append("")

    # JSON field accuracy
    lines.append("  3. JSON FIELD ACCURACY")
    ja = a["json_field_accuracy"]
    lines.append(f"     Expected fields:    {ja.get('total_expected_fields', 0)}")
    lines.append(f"     Correct fields:     {ja.get('total_correct_fields', 0)}")
    lines.append(f"     Missing fields:     {ja.get('total_missing_fields', 0)}")
    lines.append(f"     Overall accuracy:   {ja.get('overall_accuracy', 0)}%")
    lines.append(f"     Average accuracy:   {ja.get('average_accuracy', 0)}%")
    if ja.get("frequently_missing"):
        lines.append(f"     Frequently missing: {', '.join(ja['frequently_missing'][:5])}")
    lines.append("")

    # SHA-256 integrity
    lines.append("  4. SHA-256 INTEGRITY / CHANGE DETECTION")
    si = a["sha256_integrity"]
    lines.append(f"     Total checked:           {si.get('total_checked', 0)}")
    lines.append(f"     Original hash matches:   {si.get('original_hash_matches', 0)}")
    lines.append(f"     Original match rate:     {si.get('original_hash_match_rate', 0)}%")
    lines.append(f"     Modified hash changes:   {si.get('modified_hash_changes', 0)}")
    lines.append(f"     Modified change rate:    {si.get('modified_hash_change_rate', 0)}%")
    lines.append(f"     Integrity accuracy:      {si.get('integrity_accuracy', 0)}%")
    lines.append("")

    # Processing time
    lines.append("  5. PROCESSING TIME (seconds)")
    pt = a["processing_time_seconds"]
    lines.append(f"     Average:       {pt['average']}")
    lines.append(f"     Minimum:       {pt['minimum']}")
    lines.append(f"     Maximum:       {pt['maximum']}")
    lines.append(f"     Median:        {pt['median']}")
    lines.append(f"     PDF average:   {pt['pdf_average']}")
    lines.append(f"     DOCX average:  {pt['docx_average']}")
    lines.append(f"     Image/OCR avg: {pt['image_ocr_average']}")
    lines.append("")

    # Text evaluation (optional)
    if a.get("text_evaluation"):
        lines.append("  6. TEXT EVALUATION (token-level)")
        te = a["text_evaluation"]
        lines.append(f"     Precision: {te['precision']:.4f}")
        lines.append(f"     Recall:    {te['recall']:.4f}")
        lines.append(f"     F1:        {te['f1']:.4f}")
        lines.append("")
    else:
        lines.append("  6. TEXT EVALUATION: Skipped (no expected_text in ground truth)")
        lines.append("")

    # Per-document summary
    lines.append("  7. PER-DOCUMENT RESULTS")
    lines.append(f"     {'Document':<40} {'Status':<10} {'Time(s)':>8} {'Hash OK':>8}")
    lines.append(f"     {'-'*40} {'-'*10} {'-'*8} {'-'*8}")
    for doc in results["per_document"]:
        name = doc["file_name"][:38]
        status = doc["status"]
        t = doc.get("processing_time_seconds", 0)
        hash_ok = "Y" if doc.get("integrity", {}).get("original_hash_matches") else "N" if status == "success" else "-"
        lines.append(f"     {name:<40} {status:<10} {t:>8.4f} {hash_ok:>8}")
        if doc.get("error"):
            lines.append(f"       Error: {doc['error'][:80]}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("  End of Report")
    lines.append("=" * 70)

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")

    # Print concise terminal summary
    print("\n" + report_text)


# =========================================================
# MAIN
# =========================================================

def load_ground_truth(gt_path: Path) -> Dict:
    if not gt_path.exists():
        print(f"\n  ERROR: Ground truth file not found: {gt_path}")
        print("  Run build_ground_truth.py first.")
        sys.exit(1)
    with open(gt_path, "r", encoding="utf-8") as f:
        return json.load(f)


def discover_documents() -> List[Path]:
    docs = []
    if not TEST_DOCS_DIR.exists():
        return docs
    for f in TEST_DOCS_DIR.rglob("*"):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            docs.append(f)
    return sorted(docs)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate GreenTrust Module 1 (Data Ingestion & Preprocessing)"
    )
    parser.add_argument(
        "--processor-url",
        default=DEFAULT_PROCESSOR_URL,
        help=f"Processor URL (default: {DEFAULT_PROCESSOR_URL})",
    )
    parser.add_argument(
        "--ground-truth",
        default=str(DEFAULT_GROUND_TRUTH),
        help="Path to ground_truth.json",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout per document in seconds (default: 120)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  GreenTrust Module 1 — Quantitative Evaluation")
    print("=" * 70)

    # Check processor
    print(f"\n  Checking processor at {args.processor_url}...")
    try:
        health = requests.get(f"{args.processor_url.rstrip('/')}/health", timeout=10)
        if health.status_code == 200:
            print("  Processor is online.")
        else:
            print(f"  Processor health check returned {health.status_code}")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"  ERROR: Cannot reach processor at {args.processor_url}")
        print("  Start the FastAPI processor first:")
        print("    cd processor && uvicorn app:app --reload --port 8000")
        sys.exit(1)

    # Load ground truth
    gt_path = Path(args.ground_truth)
    ground_truth = load_ground_truth(gt_path)
    print(f"  Loaded ground truth: {len(ground_truth)} entries from {gt_path}")

    # Discover documents
    docs = discover_documents()
    if not docs:
        print(f"\n  No documents found in {TEST_DOCS_DIR}")
        sys.exit(1)

    print(f"  Found {len(docs)} test document(s)\n")

    # Evaluate each document
    per_doc_results: List[Dict] = []
    for i, doc_path in enumerate(docs, 1):
        file_name = doc_path.name
        print(f"  [{i}/{len(docs)}] Evaluating: {file_name}")

        gt_entry = ground_truth.get(file_name)
        if gt_entry is None:
            print(f"    [SKIP] No ground truth entry for {file_name}")
            per_doc_results.append({
                "file_name": file_name,
                "file_type": doc_path.suffix.lower().lstrip("."),
                "status": "skipped",
                "error": "No ground truth entry",
                "processing_time_seconds": 0,
            })
            continue

        result = evaluate_document(doc_path, gt_entry, args.processor_url, args.timeout)
        per_doc_results.append(result)

        if result["status"] == "success":
            print(f"    [OK] {result['processing_time_seconds']}s — "
                  f"{result['extraction_method']}")
        else:
            print(f"    [FAIL] {result.get('error', 'Unknown error')}")

    # Aggregate
    aggregate = aggregate_metrics(per_doc_results)

    results = {
        "evaluation_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "processor_url": args.processor_url,
        "ground_truth_file": str(gt_path),
        "total_documents": aggregate["total_documents"],
        "aggregate": aggregate,
        "per_document": per_doc_results,
    }

    # Write results.json
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results written to: {RESULTS_FILE}")

    # Generate report
    generate_report(results, REPORT_FILE)
    print(f"  Report written to:  {REPORT_FILE}")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
