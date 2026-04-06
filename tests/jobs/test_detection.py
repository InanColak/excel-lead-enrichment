"""FILE-03: Column detection engine unit tests.

Pure-function tests -- no database, no async needed.
"""

from app.jobs.detection import (
    _match_header,
    _normalize_header,
    detect_column_types,
    get_contact_identifier_columns,
)


# ── Header matching tests ─────────────────────────────────────────────────


def test_detect_email_header():
    """Detects 'Email' header as email type with HIGH confidence when content confirms."""
    headers = ["Email"]
    rows = [
        {"Email": "john@example.com"},
        {"Email": "jane@smith.co"},
        {"Email": "bob@wilson.io"},
    ]
    result = detect_column_types(headers, rows)
    assert len(result) == 1
    assert result[0]["detected_type"] == "email"
    assert result[0]["confidence"] == "HIGH"


def test_detect_email_variations():
    """Detects 'E-mail', 'email address', 'Mail' headers as email type."""
    for header in ["E-mail", "email address", "Mail"]:
        headers = [header]
        rows = [{header: "test@example.com"}, {header: "other@test.co"}]
        result = detect_column_types(headers, rows)
        assert result[0]["detected_type"] == "email", f"Failed for header: {header}"


def test_detect_name_headers():
    """Detects 'First Name', 'fname', 'first' as first_name type."""
    for header in ["First Name", "fname", "first"]:
        headers = [header]
        rows = [{header: "John"}, {header: "Jane"}]
        result = detect_column_types(headers, rows)
        assert result[0]["detected_type"] == "first_name", f"Failed for header: {header}"


def test_detect_last_name_headers():
    """Detects 'Last Name', 'lname', 'surname' as last_name type."""
    for header in ["Last Name", "lname", "surname"]:
        headers = [header]
        rows = [{header: "Doe"}, {header: "Smith"}]
        result = detect_column_types(headers, rows)
        assert result[0]["detected_type"] == "last_name", f"Failed for header: {header}"


def test_detect_company_headers():
    """Detects 'Company', 'Organization', 'org' as company type."""
    for header in ["Company", "Organization", "org"]:
        headers = [header]
        rows = [{header: "Acme Corp"}, {header: "Globex"}]
        result = detect_column_types(headers, rows)
        assert result[0]["detected_type"] == "company", f"Failed for header: {header}"


def test_detect_linkedin_header():
    """Detects 'LinkedIn', 'LinkedIn URL' as linkedin_url type."""
    for header in ["LinkedIn", "LinkedIn URL"]:
        headers = [header]
        rows = [
            {header: "linkedin.com/in/johndoe"},
            {header: "linkedin.com/in/janesmith"},
        ]
        result = detect_column_types(headers, rows)
        assert result[0]["detected_type"] == "linkedin_url", f"Failed for header: {header}"


def test_detect_phone_header():
    """Detects 'Phone', 'Mobile', 'Cell' as phone type."""
    for header in ["Phone", "Mobile", "Cell"]:
        headers = [header]
        rows = [{header: "+1-555-0100"}, {header: "555-0101"}]
        result = detect_column_types(headers, rows)
        assert result[0]["detected_type"] == "phone", f"Failed for header: {header}"


# ── Content sampling tests ────────────────────────────────────────────────


def test_detect_email_by_content():
    """Detects email column from content when header is ambiguous."""
    headers = ["Contact Info"]
    rows = [
        {"Contact Info": "john@example.com"},
        {"Contact Info": "jane@smith.co"},
        {"Contact Info": "bob@wilson.io"},
    ]
    result = detect_column_types(headers, rows)
    assert result[0]["detected_type"] == "email"
    assert result[0]["confidence"] == "MEDIUM"  # content-only detection capped at MEDIUM


def test_detect_linkedin_by_content():
    """Detects linkedin_url from URLs containing 'linkedin.com/in/'."""
    headers = ["Profile"]
    rows = [
        {"Profile": "https://linkedin.com/in/johndoe"},
        {"Profile": "https://linkedin.com/in/janesmith"},
        {"Profile": "https://linkedin.com/in/bobwilson"},
    ]
    result = detect_column_types(headers, rows)
    assert result[0]["detected_type"] == "linkedin_url"


def test_detect_phone_by_content():
    """Detects phone from numeric patterns in content."""
    headers = ["Data"]
    rows = [
        {"Data": "+1-555-0100"},
        {"Data": "555-0101"},
        {"Data": "(555) 010-0102"},
    ]
    result = detect_column_types(headers, rows)
    assert result[0]["detected_type"] == "phone"


# ── Confidence level tests ────────────────────────────────────────────────


def test_high_confidence_header_plus_content():
    """HIGH confidence when header and content both match."""
    headers = ["Email"]
    rows = [
        {"Email": "john@example.com"},
        {"Email": "jane@smith.co"},
    ]
    result = detect_column_types(headers, rows)
    assert result[0]["confidence"] == "HIGH"


def test_medium_confidence_header_only():
    """MEDIUM confidence when only header matches but content doesn't confirm."""
    headers = ["Email"]
    rows = [
        {"Email": "not-an-email"},
        {"Email": "also-not-email"},
    ]
    result = detect_column_types(headers, rows)
    assert result[0]["detected_type"] == "email"
    assert result[0]["confidence"] == "MEDIUM"


def test_unknown_type_no_match():
    """UNKNOWN type and confidence when nothing matches."""
    headers = ["Gibberish Column"]
    rows = [
        {"Gibberish Column": "random text"},
        {"Gibberish Column": "more random"},
    ]
    result = detect_column_types(headers, rows)
    assert result[0]["detected_type"] == "unknown"
    assert result[0]["confidence"] == "UNKNOWN"


# ── Edge case tests ───────────────────────────────────────────────────────


def test_empty_headers():
    """Handles empty header list gracefully."""
    result = detect_column_types([], [])
    assert result == []


def test_empty_rows():
    """Handles empty sample rows gracefully."""
    headers = ["Email"]
    result = detect_column_types(headers, [])
    # Header matches but no content to confirm
    assert result[0]["detected_type"] == "email"
    assert result[0]["confidence"] == "MEDIUM"


def test_header_normalization():
    """Headers with mixed case, extra spaces, underscores are normalized."""
    assert _normalize_header("  First_Name  ") == "first name"
    assert _normalize_header("E-mail") == "e mail"
    assert _normalize_header("COMPANY") == "company"
    assert _normalize_header("LinkedIn_URL") == "linkedin url"


def test_header_match_normalized():
    """_match_header works on already-normalized headers."""
    assert _match_header("first name") == "first_name"
    assert _match_header("email") == "email"
    assert _match_header("company") == "company"
    assert _match_header("linkedin url") == "linkedin_url"
    assert _match_header("xyzzy") is None


def test_contact_identifier_columns():
    """get_contact_identifier_columns returns correct set."""
    identifiers = get_contact_identifier_columns()
    assert "email" in identifiers
    assert "first_name" in identifiers
    assert "last_name" in identifiers
    assert "full_name" in identifiers
    assert "linkedin_url" in identifiers
    assert "company" in identifiers
    # phone and domain are NOT contact identifiers
    assert "phone" not in identifiers
    assert "domain" not in identifiers
    assert "unknown" not in identifiers


def test_multiple_columns_detection():
    """Multiple columns are detected correctly in a single call."""
    headers = ["First Name", "Last Name", "Email", "Company"]
    rows = [
        {"First Name": "John", "Last Name": "Doe", "Email": "john@example.com", "Company": "Acme"},
        {"First Name": "Jane", "Last Name": "Smith", "Email": "jane@smith.co", "Company": "Globex"},
    ]
    result = detect_column_types(headers, rows)
    assert len(result) == 4
    types = {r["column"]: r["detected_type"] for r in result}
    assert types["First Name"] == "first_name"
    assert types["Last Name"] == "last_name"
    assert types["Email"] == "email"
    assert types["Company"] == "company"
