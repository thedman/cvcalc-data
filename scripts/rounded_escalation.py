"""Optional rounded CPI evidence on a canonical nominal rate row."""
from datetime import date
import re
from urllib.parse import urlsplit

BASIS = "rounded-cpi-v1"


def validate_escalation(row):
    if "roundedEscalation" not in row:
        return
    evidence = row["roundedEscalation"]
    if not isinstance(evidence, dict) or evidence.get("basis") != BASIS:
        raise ValueError("invalid rounded escalation basis or evidence")
    if any(evidence.get(key) != row[key] for key in ("monthKey", "i1", "i2")):
        raise ValueError("rounded escalation evidence does not match the canonical month and nominal pair")
    for field in ("i1", "i2", "first", "later"):
        value = evidence.get(field)
        if type(value) not in (int, float) or not (0 <= value < 1):
            raise ValueError(f"invalid rounded escalation evidence field {field}")
        if field in ("first", "later") and abs(value * 1000 - round(value * 1000)) > 1e-8:
            raise ValueError(f"{field} is not a published rounded tier")
    source_url = evidence.get("sourceURL")
    if not isinstance(source_url, str):
        raise ValueError("rounded tier source URL is missing or malformed")
    url = urlsplit(source_url)
    if url.scheme != "https" or url.hostname not in {"convyta.com", "www.convyta.com"}:
        raise ValueError("rounded tier source must be hosted by Convyta over HTTPS")
    fingerprint = evidence.get("sourceSHA256")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("rounded tier source fingerprint is missing or malformed")
    if evidence.get("fingerprintKind") not in {"pdf-file", "extracted-pdf-text"}:
        raise ValueError("unknown source fingerprint kind")
    published = evidence.get("publicationDate")
    if not isinstance(published, str) or date.fromisoformat(published).isoformat() != published:
        raise ValueError("invalid source publication date")
