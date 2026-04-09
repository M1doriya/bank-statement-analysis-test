from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Pattern

from core_utils import safe_float


RULES_DIR = Path(__file__).resolve().parent / "rules"
CLASSIFICATION_RULES_FILE = RULES_DIR / "CLASSIFICATION_RULES_V3.json"
SYSTEM_PROMPT_FILE = RULES_DIR / "SYSTEM_PROMPT_v3.md"
SCHEMA_FILE = RULES_DIR / "BANK_ANALYSIS_SCHEMA_v6_3_0.json"

_TRANSFER_KEYWORDS = (
    "IBG CREDIT",
    "DUITNOW TO ACCOUNT",
    "TRANSFER TO A/C",
    "I-FUNDS TR FROM",
    "TR IBG",
    "TR TO C/A",
    "TRANSFER FR A/C",
)
_SALARY_HINTS = (
    "SALARY",
    "GAJI",
    "STAFF SALARY",
    "STAFF INCENTIVE",
    "STAFF OVERTIME",
    "STAFF BONUS",
    "STAFF ADVANCE",
    "EXTRA SALARY",
    "GUARD SALARY",
)
_ENTITY_STOPWORDS = {
    "SDN",
    "BHD",
    "BERHAD",
    "LTD",
    "LIMITED",
    "CO",
    "COMPANY",
    "INC",
    "PLC",
    "PLT",
    "PT",
    "PTY",
    "AND",
    "THE",
    "ENTERPRISE",
    "ENTERPRISES",
    "TRADING",
    "SERVICES",
    "SERVICE",
    "M",
}


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _priority_rank(priority: Any) -> int:
    text = str(priority or "").strip().upper()
    match = re.match(r"P(\d+)", text)
    if match:
        return int(match.group(1))
    return 999


def _extract_quoted_tokens(text: str) -> List[str]:
    if not text:
        return []
    out: List[str] = []
    for token in re.findall(r"'([^']+)'|\"([^\"]+)\"", text):
        value = (token[0] or token[1] or "").strip()
        if len(value) < 3:
            continue
        out.append(value.upper())
    return out


def _extract_upper_terms(text: str) -> List[str]:
    if not text:
        return []
    out: List[str] = []
    for piece in re.split(r"[\n,;/]|\\n", text):
        value = piece.strip().strip("•-*").strip()
        if len(value) < 3:
            continue
        if "[" in value or "]" in value or "(" in value or ")" in value:
            continue
        if any(ch.isalpha() for ch in value):
            out.append(value.upper())
    return out


def _extract_regex_literals(text: str) -> List[str]:
    r"""Extract literal regex patterns from freeform rulebook cells.

    Accepts lines like:
    - r"(?:EPF|KWSP)"
    - CIMB: r"AUTOPAY DR U\d{4}"
    - re.search(r"(IBG CREDIT|DUITNOW)", desc, re.I)
    """
    if not text:
        return []

    out: List[str] = []
    # r"..." / r'...'
    out.extend(m.group(1) for m in re.finditer(r"\br\"((?:\\.|[^\"])*)\"", text))
    out.extend(m.group(1) for m in re.finditer(r"\br'((?:\\.|[^'])*)'", text))

    # ...re.search(r"...", ...)
    out.extend(m.group(1) for m in re.finditer(r"re\.search\(\s*r\"((?:\\.|[^\"])*)\"", text))
    out.extend(m.group(1) for m in re.finditer(r"re\.search\(\s*r'((?:\\.|[^'])*)'", text))

    cleaned: List[str] = []
    for pat in out:
        pat = pat.strip()
        if len(pat) < 3:
            continue
        # Skip clearly dynamic/placeholder patterns that cannot be compiled safely.
        if any(marker in pat for marker in ("{" + "company", "known_factoring_entities", "monthly_eod_avg", "large_credit_threshold")):
            continue
        cleaned.append(pat)
    return cleaned


def _compile_patterns(patterns: List[str]) -> List[Pattern[str]]:
    compiled: List[Pattern[str]] = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, flags=re.IGNORECASE))
        except re.error:
            continue
    return compiled


def _description_contains_keyword(description: str, token: str) -> bool:
    if not token:
        return False
    token = token.strip().upper()
    if not token:
        return False

    # Strict phrase boundary matching for simple keyword phrases.
    if re.fullmatch(r"[A-Z0-9 /&.-]+", token):
        pattern = rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])"
        return re.search(pattern, description) is not None

    # Fallback for uncommon punctuation tokens.
    return token in description


def _normalize_entity_name(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    parts = [p for p in text.split() if p and p not in _ENTITY_STOPWORDS]
    return " ".join(parts)


def _extract_counterparty_name(description: str) -> str:
    if not description:
        return ""
    head = description.split("*")[0]
    head = re.split(r"\b(?:REF|REMARK|RM\s*\d|ID\d|ACC(?:OUNT)?\s*NO|A/C\s*NO)\b", head)[0]

    patterns = [
        r"(?:IBG CREDIT|DUITNOW TO ACCOUNT|TRANSFER TO A/C|I-FUNDS TR FROM)\s+([A-Z0-9 &./'-]{3,})",
        r"(?:TR IBG|TR TO C/A|TRANSFER FR A/C)\s+([A-Z0-9 &./'-]{3,})",
    ]
    for pat in patterns:
        m = re.search(pat, head)
        if m:
            candidate = m.group(1).strip(" -:;,.\t")
            candidate = re.sub(r"\s+", " ", candidate)
            return candidate[:120]

    return ""


def _names_match_strict(left: str, right: str) -> bool:
    left_n = _normalize_entity_name(left)
    right_n = _normalize_entity_name(right)
    if not left_n or not right_n:
        return False
    if left_n == right_n:
        return True

    # Allow conservative truncation tolerance for long legal names while
    # preventing short-root false positives (e.g., DMC TRAVEL vs DMC CONSTRUCTION).
    if len(left_n) >= 12 and len(right_n) >= 12:
        return left_n.startswith(right_n) or right_n.startswith(left_n)
    return False


def _extract_related_party_names(tx: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    raw = tx.get("related_parties")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                val = item.get("name")
            else:
                val = item
            txt = str(val or "").strip()
            if txt:
                names.append(txt)
    return names


def _matches_own_party(desc_upper: str, tx: Dict[str, Any]) -> bool:
    if not any(k in desc_upper for k in _TRANSFER_KEYWORDS):
        return False
    counterparty = _extract_counterparty_name(desc_upper)
    if not counterparty:
        return False

    company_candidates = [tx.get("company_name"), tx.get("account_holder")]
    for name in company_candidates:
        if _names_match_strict(counterparty, str(name or "")):
            return True
    return False


def _matches_related_party(desc_upper: str, tx: Dict[str, Any]) -> bool:
    related_names = _extract_related_party_names(tx)
    if not related_names:
        return False

    counterparty = _extract_counterparty_name(desc_upper)
    if not counterparty:
        return False

    # C01/C02 priority over C03/C04.
    if _matches_own_party(desc_upper, tx):
        return False

    for rp in related_names:
        if _names_match_strict(counterparty, rp):
            return True
    return False


@lru_cache(maxsize=1)
def load_rulebook() -> List[Dict[str, Any]]:
    payload = _safe_read_json(CLASSIFICATION_RULES_FILE)
    rows = payload.get("sheets", {}).get("1. Categories", {}).get("rows", []) if isinstance(payload, dict) else []

    rules: List[Dict[str, Any]] = []
    for row in rows:
        cat = str(row.get("Cat#", "")).strip().upper()
        if not re.fullmatch(r"C\d{2}", cat):
            continue

        side = str(row.get("Side", "")).strip().upper()
        if side not in {"CR", "DR"}:
            side = ""

        keyword_patterns = str(row.get("Keyword Patterns", "") or "")
        regex_source = str(row.get("Regex Pattern (Python)", "") or "")

        tokens = []
        tokens.extend(_extract_quoted_tokens(keyword_patterns))
        tokens.extend(_extract_quoted_tokens(regex_source))
        tokens.extend(_extract_upper_terms(keyword_patterns))

        seen = set()
        normalized_tokens: List[str] = []
        for token in tokens:
            t = re.sub(r"\s+", " ", token).strip()
            if len(t) < 3:
                continue
            if t in seen:
                continue
            seen.add(t)
            normalized_tokens.append(t)

        regex_patterns = _extract_regex_literals(regex_source)
        compiled_patterns = _compile_patterns(regex_patterns)

        rules.append(
            {
                "cat": cat,
                "category": row.get("Category"),
                "schema_field": row.get("Schema Field"),
                "side": side,
                "priority": row.get("Priority"),
                "priority_rank": _priority_rank(row.get("Priority")),
                "row_number": int(row.get("_row_number", 0) or 0),
                "tokens": normalized_tokens[:60],
                "regex_patterns": compiled_patterns,
            }
        )

    return sorted(rules, key=lambda r: (r["priority_rank"], r["row_number"], r["cat"]))


def classify_transaction(tx: Dict[str, Any]) -> Dict[str, Any]:
    description = str(tx.get("description", "") or "").upper()
    credit = safe_float(tx.get("credit", 0))
    debit = safe_float(tx.get("debit", 0))

    tx_side = "CR" if credit > 0 else ("DR" if debit > 0 else "")
    if not description or not tx_side:
        return {}

    for rule in load_rulebook():
        cat = str(rule.get("cat") or "")
        rule_side = rule.get("side") or ""
        if rule_side and rule_side != tx_side:
            continue

        # Enforce tighter own-party / related-party logic per rulebook.
        if cat in {"C01", "C02"}:
            if not _matches_own_party(description, tx):
                continue
            return {
                "rule_category_code": cat,
                "rule_category_name": rule.get("category"),
                "rule_schema_field": rule.get("schema_field"),
                "rule_match_side": tx_side,
            }

        if cat in {"C03", "C04"}:
            if cat == "C04" and any(h in description for h in _SALARY_HINTS):
                # C05 must outrank C04 for salary-tagged transfers.
                continue
            if not _matches_related_party(description, tx):
                continue
            return {
                "rule_category_code": cat,
                "rule_category_name": rule.get("category"),
                "rule_schema_field": rule.get("schema_field"),
                "rule_match_side": tx_side,
            }

        regex_patterns: List[Pattern[str]] = rule.get("regex_patterns", [])
        regex_hit = any(p.search(description) for p in regex_patterns)

        tokens = rule.get("tokens", [])
        token_hit = any(_description_contains_keyword(description, token) for token in tokens)

        if regex_hit or token_hit:
            return {
                "rule_category_code": rule.get("cat"),
                "rule_category_name": rule.get("category"),
                "rule_schema_field": rule.get("schema_field"),
                "rule_match_side": tx_side,
            }
    return {}


@lru_cache(maxsize=1)
def get_rules_metadata() -> Dict[str, Any]:
    schema = _safe_read_json(SCHEMA_FILE)
    prompt = _safe_read_text(SYSTEM_PROMPT_FILE)
    rulebook = load_rulebook()
    return {
        "schema_version": schema.get("properties", {}).get("report_info", {}).get("properties", {}).get("schema_version", {}).get("const"),
        "rule_count": len(rulebook),
        "classification_file": str(CLASSIFICATION_RULES_FILE),
        "schema_file": str(SCHEMA_FILE),
        "system_prompt_file": str(SYSTEM_PROMPT_FILE),
        "system_prompt_loaded": bool(prompt.strip()),
    }
