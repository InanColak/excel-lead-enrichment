"""Column type detection engine for Excel file processing.

Pure-function module with NO database access, NO async.
Detects column types from headers and content sampling with confidence scoring.
"""

import re

# Recognized column types
COLUMN_TYPES = [
    "first_name",
    "last_name",
    "full_name",
    "company",
    "email",
    "linkedin_url",
    "phone",
    "domain",
    "unknown",
]

# Confidence levels: HIGH = header + content, MEDIUM = one match, LOW = heuristic, UNKNOWN = nothing
CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]

# Header matching patterns (case-insensitive, whitespace-normalized)
HEADER_PATTERNS: dict[str, list[str]] = {
    "first_name": ["first name", "fname", "first", "given name", "first_name"],
    "last_name": ["last name", "lname", "last", "surname", "family name", "last_name"],
    "full_name": ["full name", "name", "contact name", "full_name", "person"],
    "company": ["company", "organization", "org", "employer", "company name", "business"],
    "email": ["email", "e-mail", "email address", "mail"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile", "li url", "linkedin_url"],
    "phone": ["phone", "mobile", "cell", "telephone", "phone number", "mobile phone"],
    "domain": ["domain", "website", "web", "url", "company domain", "company url"],
}

# Content sampling regex patterns
CONTENT_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"),
    "linkedin_url": re.compile(r"linkedin\.com/in/"),
    "phone": re.compile(r"^[\+]?[\d\s\-\(\)\.]{7,20}$"),
    "domain": re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$"),
}

# Maximum number of sample values to inspect per column
_MAX_SAMPLE_SIZE = 20


def _normalize_header(header: str) -> str:
    """Normalize a column header for matching.

    Lowercases, strips whitespace, and replaces common separators with spaces.
    """
    normalized = header.lower().strip()
    # Replace underscores, hyphens, and multiple spaces with single space
    normalized = re.sub(r"[_\-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _match_header(normalized_header: str) -> str | None:
    """Match a normalized header against known patterns.

    Returns the column type string if matched, None otherwise.
    """
    for col_type, patterns in HEADER_PATTERNS.items():
        for pattern in patterns:
            if normalized_header == pattern:
                return col_type
    return None


def _sample_column_values(
    header: str, sample_rows: list[dict], max_samples: int = _MAX_SAMPLE_SIZE
) -> list[str]:
    """Extract up to max_samples non-empty string values for a column from sample rows."""
    values: list[str] = []
    for row in sample_rows:
        if len(values) >= max_samples:
            break
        val = row.get(header)
        if val is not None:
            str_val = str(val).strip()
            if str_val:
                values.append(str_val)
    return values


def _detect_content_type(values: list[str]) -> tuple[str | None, float]:
    """Detect column type from content values using regex patterns.

    Returns (type, match_ratio) where match_ratio is the fraction of values matching.
    """
    if not values:
        return None, 0.0

    best_type: str | None = None
    best_ratio: float = 0.0

    for col_type, pattern in CONTENT_PATTERNS.items():
        matches = sum(1 for v in values if pattern.search(v))
        ratio = matches / len(values)
        if ratio > best_ratio:
            best_ratio = ratio
            best_type = col_type

    return best_type, best_ratio


def detect_column_types(
    headers: list[str], sample_rows: list[dict]
) -> list[dict]:
    """Detect column types from headers and content sampling.

    Args:
        headers: Column header names from the Excel file.
        sample_rows: First N non-empty rows as dicts keyed by header name.

    Returns:
        List of dicts: [{"column": header, "detected_type": type, "confidence": level}, ...]

    Detection logic per column:
        1. Normalize header (lowercase, strip, replace separators).
        2. Header match -> MEDIUM confidence.
        3. If header matched, sample content with regex:
           - If content confirms header type -> upgrade to HIGH.
           - If content contradicts -> keep MEDIUM (header wins).
        4. If NO header match, content-only detection:
           - >50% match -> MEDIUM confidence.
        5. Nothing matches -> unknown / UNKNOWN.
    """
    results: list[dict] = []

    for header in headers:
        normalized = _normalize_header(header)
        header_type = _match_header(normalized)

        if header_type is not None:
            # Header matched -- start at MEDIUM confidence
            detected_type = header_type
            confidence = "MEDIUM"

            # Try to upgrade via content sampling if regex pattern exists
            if header_type in CONTENT_PATTERNS:
                values = _sample_column_values(header, sample_rows)
                if values:
                    matches = sum(
                        1 for v in values if CONTENT_PATTERNS[header_type].search(v)
                    )
                    ratio = matches / len(values)
                    if ratio > 0.5:
                        confidence = "HIGH"
                    # If content contradicts, keep MEDIUM -- header wins
        else:
            # No header match -- try content-only detection
            values = _sample_column_values(header, sample_rows)
            content_type, match_ratio = _detect_content_type(values)

            if content_type is not None and match_ratio > 0.5:
                detected_type = content_type
                confidence = "MEDIUM"
            else:
                detected_type = "unknown"
                confidence = "UNKNOWN"

        results.append(
            {
                "column": header,
                "detected_type": detected_type,
                "confidence": confidence,
            }
        )

    return results


def get_contact_identifier_columns() -> set[str]:
    """Column types that count as contact identifiers for malformed row detection."""
    return {"first_name", "last_name", "full_name", "email", "linkedin_url", "company"}
