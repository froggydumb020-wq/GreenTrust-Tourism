#!/usr/bin/env python3
"""
GreenTrust Module 1 Evaluation — Quantitative Evaluator

Evaluates ONLY the ACTUAL OUTPUT produced by the existing Module 1 processor.
Does NOT re-process documents to create results — it sends each document through
the existing POST /process/document endpoint and measures what Module 1 returned.

Flow: Document → Existing Module 1 → Actual Output → Evaluation → Metrics

Does NOT modify Module 1, the frontend, backend, authentication, or MongoDB.

Calculates exactly 6 metrics:
  1. Processing Success Rate
  2. Text Extraction Accuracy (P/R/F1 against verified expected_text, or N/A)
  3. Structured Information Extraction (P/R/F1 for dates, measurements,
     financials, key_data, relevant_terms)
  4. Structured JSON Correctness (verifies expected values are correctly
     placed in corresponding JSON fields — NOT just field existence)
  5. SHA-256 Integrity / Change Detection
  6. Processing Performance (average, min, max, median, per-type)

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
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
    if s is None:
        return ""
    return " ".join(str(s).lower().split())


def normalize_number(val: Any) -> Optional[float]:
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
# PRF COMPUTATION
# =========================================================

def compute_prf(tp: int, fp: int, fn: int) -> Dict[str, Any]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
    }


# =========================================================
# SET COMPARISON FOR STRUCTURED FIELDS
# =========================================================

def make_hashable(items: List[Any], kind: str) -> List[str]:
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


def compare_sets(expected: List[Any], actual: List[Any], kind: str) -> Dict:
    expected_keys = set(make_hashable(expected, kind))
    actual_keys = set(make_hashable(actual, kind))
    tp = len(expected_keys & actual_keys)
    fp = len(actual_keys - expected_keys)
    fn = len(expected_keys - actual_keys)
    return compute_prf(tp, fp, fn)


def compare_key_data(expected: Dict[str, str], actual: Dict[str, str]) -> Dict:
    expected_norm = {normalize_string(k): normalize_string(v) for k, v in expected.items()}
    actual_norm = {normalize_string(k): normalize_string(v) for k, v in actual.items()}
    all_keys = set(expected_norm.keys()) | set(actual_norm.keys())
    tp = fp = fn = 0
    for key in all_keys:
        if key in expected_norm and key in actual_norm:
            if expected_norm[key] == actual_norm[key]:
                tp += 1
            else:
                fp += 1; fn += 1
        elif key in actual_norm:
            fp += 1
        else:
            fn += 1
    return compute_prf(tp, fp, fn)


# =========================================================
# METRIC 4: STRUCTURED JSON CORRECTNESS
# Checks that expected VALUES are correctly placed in the
# corresponding JSON fields — NOT just field existence.
# =========================================================

# Maps ground-truth field → JSON path in structured_data
JSON_FIELD_MAP = {
    "dates": "structured_data.dates",
    "measurements": "structured_data.measurements",
    "financials": "structured_data.financials",
    "key_data": "structured_data.key_data",
    "relevant_terms": "structured_data.relevant_terms",
}


def get_nested(d: Dict, path: str) -> Any:
    parts = path.split(".")
    current = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def check_json_correctness(processor_data: Dict, gt_entry: Dict) -> Dict:
    """
    For each ground-truth field, check whether Module 1 placed the
    correct values in the corresponding structured_data JSON field.

    A field is 'correct' if the expected values from ground truth are
    actually present in the processor's output for that field.
    A field is 'missing' if the JSON path doesn't exist or is empty.
    A field is 'incorrect' if it exists but expected values are absent.
    """
    total_expected = 0
    correct = 0
    missing = 0
    incorrect = 0
    details = {}

    for gt_field, json_path in JSON_FIELD_MAP.items():
        expected_values = gt_entry.get(gt_field, [])
        if not expected_values:
            continue

        total_expected += 1

        actual_values = get_nested(processor_data, json_path)
        if actual_values is None or actual_values == [] or actual_values == {}:
            missing += 1
            details[gt_field] = {
                "status": "missing",
                "json_path": json_path,
                "expected_count": len(expected_values) if isinstance(expected_values, list) else len(expected_values),
            }
            continue

        # Check if expected values are present in actual output
        if gt_field == "key_data":
            expected_norm = {normalize_string(k): normalize_string(v) for k, v in expected_values.items()}
            actual_norm = {normalize_string(k): normalize_string(v) for k, v in actual_values.items()}
            matches = sum(1 for k, v in expected_norm.items() if k in actual_norm and actual_norm[k] == v)
            is_correct = matches > 0
        else:
            expected_keys = set(make_hashable(expected_values, gt_field))
            actual_keys = set(make_hashable(actual_values, gt_field))
            matches = len(expected_keys & actual_keys)
            is_correct = matches > 0

        if is_correct:
            correct += 1
            details[gt_field] = {
                "status": "correct",
                "json_path": json_path,
                "expected_count": len(expected_values) if isinstance(expected_values, list) else len(expected_values),
                "matched_count": matches,
            }
        else:
            incorrect += 1
            details[gt_field] = {
                "status": "incorrect",
                "json_path": json_path,
                "expected_count": len(expected_values) if isinstance(expected_values, list) else len(expected_values),
                "matched_count": 0,
            }

    accuracy = round(correct / total_expected * 100, 2) if total_expected > 0 else 0.0

    return {
        "expected_fields": total_expected,
        "correct_fields": correct,
        "missing_fields": missing,
        "incorrect_fields": incorrect,
        "accuracy": accuracy,
        "details": details,
    }


# =========================================================
# METRIC 5: SHA-256 INTEGRITY / CHANGE DETECTION
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
    original_hash = compute_sha256(file_path)
    original_matches = (original_hash == processor_hash)

    modified_hash = None
    modified_differs = False
    try:
        data = bytearray(file_path.read_bytes())
        if len(data) > 0:
            data[-1] ^= 0xFF
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
# METRIC 2: TEXT EXTRACTION ACCURACY
# =========================================================

def tokenize(text: str) -> Set[str]:
    return set(text.lower().split())


def evaluate_text(expected_text: str, actual_text: str) -> Dict:
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
        return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:500]}"}
    return {"success": True, "data": response.json()}


# =========================================================
# PER-DOCUMENT EVALUATION
# =========================================================

def evaluate_document(
    file_path: Path, gt_entry: Dict, processor_url: str, timeout: int,
) -> Dict:
    result: Dict[str, Any] = {
        "file_name": file_path.name,
        "file_type": file_path.suffix.lower().lstrip("."),
    }

    # Send to Module 1 processor — this is the ONLY processing done
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

    # Capture ACTUAL Module 1 output
    result["extraction_method"] = data.get("extraction_method", "")
    result["confidence"] = data.get("confidence", 0)
    result["sha256_returned"] = data.get("sha256", "")

    structured = data.get("structured_data", {})
    metadata = data.get("metadata", {})

    # METRIC 3: Structured Information Extraction (P/R/F1)
    gt_dates = gt_entry.get("dates", [])
    actual_dates = structured.get("dates", []) or metadata.get("detected_dates", [])
    result["dates"] = compare_sets(gt_dates, actual_dates, "dates")

    gt_measurements = gt_entry.get("measurements", [])
    actual_measurements = structured.get("measurements", [])
    result["measurements"] = compare_sets(gt_measurements, actual_measurements, "measurements")

    gt_financials = gt_entry.get("financials", [])
    actual_financials = structured.get("financials", [])
    result["financials"] = compare_sets(gt_financials, actual_financials, "financials")

    gt_key_data = gt_entry.get("key_data", {})
    actual_key_data = structured.get("key_data", {})
    result["key_data"] = compare_key_data(gt_key_data, actual_key_data)

    gt_terms = gt_entry.get("relevant_terms", [])
    actual_terms = structured.get("relevant_terms", []) or metadata.get("relevant_detected_terms", [])
    result["relevant_terms"] = compare_sets(gt_terms, actual_terms, "relevant_terms")

    # METRIC 4: Structured JSON Correctness (value placement, not just existence)
    result["json_correctness"] = check_json_correctness(data, gt_entry)

    # METRIC 5: SHA-256 Integrity / Change Detection
    result["integrity"] = verify_integrity(file_path, data.get("sha256", ""))

    # METRIC 2: Text Extraction Accuracy (or N/A)
    if "expected_text" in gt_entry and gt_entry["expected_text"]:
        actual_text = data.get("extracted_text", "")
        result["text_extraction"] = evaluate_text(gt_entry["expected_text"], actual_text)
    else:
        result["text_extraction"] = None

    return result


# =========================================================
# AGGREGATE METRICS
# =========================================================

def aggregate_prf(field_results: List[Dict]) -> Dict:
    total_tp = sum(r["tp"] for r in field_results)
    total_fp = sum(r["fp"] for r in field_results)
    total_fn = sum(r["fn"] for r in field_results)
    return compute_prf(total_tp, total_fp, total_fn)


def aggregate_metrics(per_doc_results: List[Dict]) -> Dict:
    successful = [r for r in per_doc_results if r["status"] == "success"]
    total = len(per_doc_results)
    success_count = len(successful)

    # METRIC 1: Processing Success Rate
    success_rate = round(success_count / total * 100, 2) if total > 0 else 0.0

    # METRIC 2: Text Extraction Accuracy
    text_results = [r["text_extraction"] for r in successful if r.get("text_extraction") is not None]
    docs_with_text = len(text_results)
    docs_without_text = sum(1 for r in successful if r.get("text_extraction") is None)
    if text_results:
        text_summary = aggregate_prf(text_results)
        text_summary["documents_with_expected_text"] = docs_with_text
        text_summary["documents_without_expected_text"] = docs_without_text
    else:
        text_summary = {
            "precision": "N/A", "recall": "N/A", "f1": "N/A",
            "tp": 0, "fp": 0, "fn": 0,
            "documents_with_expected_text": 0,
            "documents_without_expected_text": docs_without_text,
            "status": "No verified expected_text in ground truth",
        }

    # METRIC 3: Structured Information Extraction
    fields = ["dates", "measurements", "financials", "key_data", "relevant_terms"]
    structured: Dict[str, Any] = {}
    for field in fields:
        field_results = [r[field] for r in successful if field in r]
        structured[field] = aggregate_prf(field_results) if field_results else compute_prf(0, 0, 0)

    overall_tp = sum(structured[f]["tp"] for f in fields)
    overall_fp = sum(structured[f]["fp"] for f in fields)
    overall_fn = sum(structured[f]["fn"] for f in fields)
    structured["overall"] = compute_prf(overall_tp, overall_fp, overall_fn)

    # METRIC 4: Structured JSON Correctness
    json_results = [r["json_correctness"] for r in successful if "json_correctness" in r]
    if json_results:
        total_expected = sum(j["expected_fields"] for j in json_results)
        total_correct = sum(j["correct_fields"] for j in json_results)
        total_missing = sum(j["missing_fields"] for j in json_results)
        total_incorrect = sum(j["incorrect_fields"] for j in json_results)
        json_summary = {
            "expected_fields": total_expected,
            "correct_fields": total_correct,
            "missing_fields": total_missing,
            "incorrect_fields": total_incorrect,
            "accuracy": round(total_correct / total_expected * 100, 2) if total_expected > 0 else 0.0,
        }
    else:
        json_summary = {"expected_fields": 0, "correct_fields": 0, "missing_fields": 0, "incorrect_fields": 0, "accuracy": 0.0}

    # METRIC 5: SHA-256 Integrity / Change Detection
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

    # METRIC 6: Processing Performance
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

    return {
        "metric_1_processing_success_rate": {
            "total_documents": total,
            "successful_documents": success_count,
            "failed_documents": total - success_count,
            "success_rate": success_rate,
        },
        "metric_2_text_extraction_accuracy": text_summary,
        "metric_3_structured_extraction": structured,
        "metric_4_json_correctness": json_summary,
        "metric_5_sha256_integrity": integrity_summary,
        "metric_6_processing_performance": time_stats,
    }


# =========================================================
# REPORT GENERATION
# =========================================================

def generate_report(results: Dict, report_path: Path) -> None:
    lines: List[str] = []
    a = results["aggregate"]

    lines.append("=" * 70)
    lines.append("  GreenTrust Module 1 — Quantitative Evaluation Report")
    lines.append("  (Measures ACTUAL Module 1 output — no re-processing)")
    lines.append("=" * 70)
    lines.append("")

    # METRIC 1
    m1 = a["metric_1_processing_success_rate"]
    lines.append("  METRIC 1: PROCESSING SUCCESS RATE")
    lines.append(f"     Total documents:    {m1['total_documents']}")
    lines.append(f"     Successful:         {m1['successful_documents']}")
    lines.append(f"     Failed:             {m1['failed_documents']}")
    lines.append(f"     Success rate:       {m1['success_rate']}%")
    lines.append("")

    # METRIC 2
    m2 = a["metric_2_text_extraction_accuracy"]
    lines.append("  METRIC 2: TEXT EXTRACTION ACCURACY")
    if isinstance(m2.get("precision"), str):
        lines.append(f"     Status:             {m2.get('status', 'N/A')}")
        lines.append(f"     Docs with expected:  {m2.get('documents_with_expected_text', 0)}")
        lines.append(f"     Docs without:        {m2.get('documents_without_expected_text', 0)}")
    else:
        lines.append(f"     Precision:          {m2['precision']:.4f}")
        lines.append(f"     Recall:             {m2['recall']:.4f}")
        lines.append(f"     F1:                 {m2['f1']:.4f}")
        lines.append(f"     Docs with expected:  {m2.get('documents_with_expected_text', 0)}")
        lines.append(f"     Docs without:        {m2.get('documents_without_expected_text', 0)}")
    lines.append("")

    # METRIC 3
    lines.append("  METRIC 3: STRUCTURED INFORMATION EXTRACTION")
    lines.append(f"     {'Field':<20} {'Precision':>10} {'Recall':>10} {'F1':>10} {'TP':>5} {'FP':>5} {'FN':>5}")
    lines.append(f"     {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*5} {'-'*5} {'-'*5}")
    m3 = a["metric_3_structured_extraction"]
    for field in ["dates", "measurements", "financials", "key_data", "relevant_terms"]:
        f = m3[field]
        lines.append(f"     {field:<20} {f['precision']:>10.4f} {f['recall']:>10.4f} {f['f1']:>10.4f} {f['tp']:>5} {f['fp']:>5} {f['fn']:>5}")
    ov = m3["overall"]
    lines.append(f"     {'OVERALL':<20} {ov['precision']:>10.4f} {ov['recall']:>10.4f} {ov['f1']:>10.4f} {ov['tp']:>5} {ov['fp']:>5} {ov['fn']:>5}")
    lines.append("")

    # METRIC 4
    m4 = a["metric_4_json_correctness"]
    lines.append("  METRIC 4: STRUCTURED JSON CORRECTNESS")
    lines.append(f"     Expected fields:    {m4['expected_fields']}")
    lines.append(f"     Correct fields:     {m4['correct_fields']}")
    lines.append(f"     Missing fields:     {m4['missing_fields']}")
    lines.append(f"     Incorrect fields:   {m4['incorrect_fields']}")
    lines.append(f"     Accuracy:           {m4['accuracy']}%")
    lines.append("")

    # METRIC 5
    m5 = a["metric_5_sha256_integrity"]
    lines.append("  METRIC 5: SHA-256 INTEGRITY / CHANGE DETECTION")
    lines.append(f"     Total checked:           {m5.get('total_checked', 0)}")
    lines.append(f"     Original hash matches:   {m5.get('original_hash_matches', 0)}")
    lines.append(f"     Original match rate:     {m5.get('original_hash_match_rate', 0)}%")
    lines.append(f"     Modified hash changes:   {m5.get('modified_hash_changes', 0)}")
    lines.append(f"     Modified change rate:    {m5.get('modified_hash_change_rate', 0)}%")
    lines.append(f"     Integrity accuracy:      {m5.get('integrity_accuracy', 0)}%")
    lines.append("")

    # METRIC 6
    m6 = a["metric_6_processing_performance"]
    lines.append("  METRIC 6: PROCESSING PERFORMANCE (seconds)")
    lines.append(f"     Average:       {m6['average']}")
    lines.append(f"     Minimum:       {m6['minimum']}")
    lines.append(f"     Maximum:       {m6['maximum']}")
    lines.append(f"     Median:        {m6['median']}")
    lines.append(f"     PDF average:   {m6['pdf_average']}")
    lines.append(f"     DOCX average:  {m6['docx_average']}")
    lines.append(f"     Image/OCR avg: {m6['image_ocr_average']}")
    lines.append("")

    # PER-DOCUMENT RESULTS
    lines.append("  PER-DOCUMENT RESULTS")
    lines.append(f"     {'Document':<40} {'Status':<10} {'Time(s)':>8} {'Hash':>5} {'JSON':>6}")
    lines.append(f"     {'-'*40} {'-'*10} {'-'*8} {'-'*5} {'-'*6}")
    for doc in results["per_document"]:
        name = doc["file_name"][:38]
        status = doc["status"]
        t = doc.get("processing_time_seconds", 0)
        hash_ok = "Y" if doc.get("integrity", {}).get("original_hash_matches") else ("N" if status == "success" else "-")
        json_acc = f"{doc.get('json_correctness', {}).get('accuracy', 0):.0f}%" if status == "success" else "-"
        lines.append(f"     {name:<40} {status:<10} {t:>8.4f} {hash_ok:>5} {json_acc:>6}")
        if doc.get("error"):
            lines.append(f"       Error: {doc['error'][:80]}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("  End of Report")
    lines.append("=" * 70)

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
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
        description="Evaluate ACTUAL output of GreenTrust Module 1 (Data Ingestion & Preprocessing)"
    )
    parser.add_argument("--processor-url", default=DEFAULT_PROCESSOR_URL)
    parser.add_argument("--ground-truth", default=str(DEFAULT_GROUND_TRUTH))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  GreenTrust Module 1 — Quantitative Evaluation")
    print("  (Measures ACTUAL Module 1 output — does NOT re-process)")
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

    # Evaluate each document — send through existing Module 1
    per_doc_results: List[Dict] = []
    for i, doc_path in enumerate(docs, 1):
        file_name = doc_path.name
        print(f"  [{i}/{len(docs)}] Sending to Module 1: {file_name}")

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
            print(f"    [OK] {result['processing_time_seconds']}s — {result['extraction_method']}")
        else:
            print(f"    [FAIL] {result.get('error', 'Unknown error')}")

    # Aggregate all 6 metrics
    aggregate = aggregate_metrics(per_doc_results)

    results = {
        "evaluation_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "processor_url": args.processor_url,
        "ground_truth_file": str(gt_path),
        "total_documents": aggregate["metric_1_processing_success_rate"]["total_documents"],
        "aggregate": aggregate,
        "per_document": per_doc_results,
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results written to: {RESULTS_FILE}")

    generate_report(results, REPORT_FILE)
    print(f"  Report written to:  {REPORT_FILE}")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
