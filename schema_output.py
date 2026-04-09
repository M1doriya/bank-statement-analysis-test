from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from core_utils import normalize_date, safe_float

RULES_DIR = Path(__file__).resolve().parent / "rules"
SCHEMA_FILE = RULES_DIR / "BANK_ANALYSIS_SCHEMA_v6_3_0.json"


def _load_schema() -> Dict[str, Any]:
    try:
        return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _as_date(value: Any) -> str:
    iso = normalize_date(value)
    return iso or "1970-01-01"


def _as_month(value: Any) -> str:
    txt = str(value or "").strip()
    if len(txt) >= 7 and txt[4] == "-":
        return txt[:7]
    return "1970-01"


def _tx_amount_and_side(row: Dict[str, Any]) -> tuple[float, str]:
    credit = safe_float(row.get("credit", 0))
    debit = safe_float(row.get("debit", 0))
    if credit > 0:
        return credit, "CR"
    if debit > 0:
        return debit, "DR"
    return 0.0, ""


def _apply_category_to_month(month_rec: Dict[str, Any], category_code: str, amount: float) -> bool:
    cat = str(category_code or "").strip().upper()
    if not cat:
        return False
    if cat == "C25":
        return True

    if cat == "C01":
        month_rec["own_party_cr"] += amount
        month_rec["own_party_cr_count"] += 1
    elif cat == "C02":
        month_rec["own_party_dr"] += amount
        month_rec["own_party_dr_count"] += 1
    elif cat == "C03":
        month_rec["related_party_cr"] += amount
        month_rec["related_party_cr_count"] += 1
    elif cat == "C04":
        month_rec["related_party_dr"] += amount
        month_rec["related_party_dr_count"] += 1
    elif cat == "C05":
        month_rec["salary_paid"] += amount
    elif cat == "C06":
        month_rec["statutory_epf"] += amount
    elif cat == "C07":
        month_rec["statutory_socso"] += amount
    elif cat == "C08":
        month_rec["statutory_tax"] += amount
    elif cat == "C09":
        month_rec["statutory_hrdf"] += amount
    elif cat == "C10":
        month_rec["loan_disbursement_cr"] += amount
    elif cat == "C11":
        month_rec["loan_repayment_dr"] += amount
        month_rec["loan_repayment_count"] += 1
    elif cat == "C12":
        month_rec["fd_interest_cr"] += amount
    elif cat == "C13":
        month_rec["reversal_cr"] += amount
    elif cat == "C14":
        month_rec["returned_cheques_inward_count"] += 1
        month_rec["returned_cheques_inward_amount"] += amount
    elif cat == "C15":
        month_rec["returned_cheques_outward_count"] += 1
        month_rec["returned_cheques_outward_amount"] += amount
    elif cat == "C16":
        month_rec["inward_return_cr"] += amount
    elif cat == "C17":
        month_rec["cash_deposits_count"] += 1
        month_rec["cash_deposits_amount"] += amount
    elif cat == "C18":
        month_rec["cash_withdrawals_count"] += 1
        month_rec["cash_withdrawals_amount"] += amount
    elif cat == "C19":
        month_rec["cheque_deposits_count"] += 1
        month_rec["cheque_deposits_amount"] += amount
    elif cat == "C20":
        month_rec["cheque_issues_count"] += 1
        month_rec["cheque_issues_amount"] += amount
    elif cat == "C21":
        month_rec["round_figure_cr"] += amount
    elif cat in {"C22", "C23"}:
        month_rec["high_value_cr"] += amount
    elif cat == "C24":
        pass
    else:
        return False
    return True


def _party_rows(df: pd.DataFrame, amount_col: str, top_n: int = 5) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    work = df.copy()
    work["amount"] = work[amount_col].apply(safe_float)
    work = work[work["amount"] > 0]
    if work.empty:
        return []

    work["month"] = work.get("date", "").astype(str).str.slice(0, 7)

    grouped = work.groupby("description", dropna=False).agg(total_amount=("amount", "sum"), transaction_count=("amount", "count"))
    grouped = grouped.sort_values("total_amount", ascending=False).head(top_n)

    out: List[Dict[str, Any]] = []
    for i, (desc, row) in enumerate(grouped.iterrows(), start=1):
        party_rows = work[work["description"] == desc]
        monthly = (
            party_rows.groupby("month", dropna=False)
            .agg(amount=("amount", "sum"), count=("amount", "count"))
            .reset_index()
            .sort_values("month")
        )
        out.append(
            {
                "rank": i,
                "party_name": str(desc or "Unknown"),
                "total_amount": round(float(row["total_amount"]), 2),
                "transaction_count": int(row["transaction_count"]),
                "is_related_party": False,
                "monthly_breakdown": [
                    {
                        "month": _as_month(mr["month"]),
                        "amount": round(float(mr["amount"]), 2),
                        "count": int(mr["count"]),
                    }
                    for _, mr in monthly.iterrows()
                ],
            }
        )
    return out


def _build_accounts(df: pd.DataFrame, period_start: str, period_end: str) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    work = df.copy()
    work["account_number"] = work.get("account_no", "").fillna("").astype(str)
    work["bank_name"] = work.get("bank", "").fillna("").astype(str)

    out = []
    for (account_number, bank_name), g in work.groupby(["account_number", "bank_name"], dropna=False):
        g = g.sort_values("date")
        out.append(
            {
                "bank_name": bank_name or "Unknown Bank",
                "account_number": account_number or "Unknown Account",
                "account_holder": str(g.get("company_name", pd.Series(["Unknown"])) .dropna().astype(str).head(1).iloc[0]) if len(g) else "Unknown",
                "account_type": "Current",
                "is_od": bool((g.get("balance", pd.Series([], dtype=float)).dropna().astype(float) < 0).any()),
                "od_limit": 0.0,
                "period_start": period_start,
                "period_end": period_end,
                "opening_balance": round(float(safe_float(g.iloc[0].get("balance"))), 2) if len(g) else 0.0,
                "closing_balance": round(float(safe_float(g.iloc[-1].get("balance"))), 2) if len(g) else 0.0,
                "total_credits": round(float(g.get("credit", pd.Series([], dtype=float)).apply(safe_float).sum()), 2),
                "total_debits": round(float(g.get("debit", pd.Series([], dtype=float)).apply(safe_float).sum()), 2),
                "transaction_count": int(len(g)),
            }
        )
    return out


def build_schema_report(
    *,
    transactions: List[Dict[str, Any]],
    monthly_summary: List[Dict[str, Any]],
    rules_metadata: Dict[str, Any],
    apply_rules_v3: bool,
) -> Dict[str, Any]:
    schema = _load_schema()
    schema_version = (
        schema.get("properties", {})
        .get("report_info", {})
        .get("properties", {})
        .get("schema_version", {})
        .get("const", "6.3.0")
    )

    df = pd.DataFrame(transactions or [])
    if not df.empty:
        if "date" not in df.columns:
            df["date"] = ""
        df["date"] = df["date"].fillna("").astype(str)
        date_min = _as_date(df["date"].min())
        date_max = _as_date(df["date"].max())
    else:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        date_min = today
        date_max = today

    company_name = "Unknown"
    if not df.empty and "company_name" in df.columns:
        names = [x.strip() for x in df["company_name"].dropna().astype(str).tolist() if x.strip()]
        if names:
            company_name = sorted(set(names))[0]

    accounts = _build_accounts(df, date_min, date_max)

    monthly_analysis: List[Dict[str, Any]] = []
    bank_by_account: Dict[str, str] = {}
    if not df.empty and {"account_no", "bank"}.issubset(df.columns):
        for _, r in df.dropna(subset=["account_no"]).iterrows():
            account_no = str(r.get("account_no") or "").strip()
            bank_name = str(r.get("bank") or "").strip()
            if account_no and bank_name and account_no not in bank_by_account:
                bank_by_account[account_no] = bank_name

    for row in monthly_summary or []:
        open_bal = safe_float(row.get("opening_balance", 0))
        close_bal = safe_float(row.get("ending_balance", 0))
        gross_cr = safe_float(row.get("total_credit", 0))
        gross_dr = safe_float(row.get("total_debit", 0))
        rec_delta = round(close_bal - (open_bal + gross_cr - gross_dr), 2)
        account_no = str(row.get("account_no") or "Unknown Account")
        bank_name = str(bank_by_account.get(account_no) or "Unknown Bank")

        monthly_analysis.append(
            {
                "month": _as_month(row.get("month")),
                "account_number": account_no,
                "bank_name": bank_name,
                "gross_credits": round(gross_cr, 2),
                "gross_debits": round(gross_dr, 2),
                "net_credits": round(max(gross_cr - gross_dr, 0), 2),
                "net_debits": round(max(gross_dr - gross_cr, 0), 2),
                "credit_count": 0,
                "debit_count": 0,
                "own_party_cr": 0.0,
                "own_party_dr": 0.0,
                "related_party_cr": 0.0,
                "related_party_dr": 0.0,
                "reversal_cr": 0.0,
                "returned_cheques_inward_count": 0,
                "returned_cheques_inward_amount": 0.0,
                "returned_cheques_outward_count": 0,
                "returned_cheques_outward_amount": 0.0,
                "loan_disbursement_cr": 0.0,
                "fd_interest_cr": 0.0,
                "round_figure_cr": 0.0,
                "high_value_cr": 0.0,
                "cash_deposits_count": 0,
                "cash_deposits_amount": 0.0,
                "cash_withdrawals_count": 0,
                "cash_withdrawals_amount": 0.0,
                "cheque_deposits_count": 0,
                "cheque_deposits_amount": 0.0,
                "cheque_issues_count": 0,
                "cheque_issues_amount": 0.0,
                "loan_repayment_dr": 0.0,
                "salary_paid": 0.0,
                "statutory_epf": 0.0,
                "statutory_socso": 0.0,
                "statutory_tax": 0.0,
                "statutory_hrdf": 0.0,
                "eod_lowest": round(float(safe_float(row.get("lowest_balance", 0))), 2),
                "eod_highest": round(float(safe_float(row.get("highest_balance", 0))), 2),
                "eod_average": round((safe_float(row.get("highest_balance", 0)) + safe_float(row.get("lowest_balance", 0))) / 2, 2),
                "opening_balance": round(open_bal, 2),
                "closing_balance": round(close_bal, 2),
                "fx_credit_count": 0,
                "fx_credit_amount": 0.0,
                "fx_debit_count": 0,
                "fx_debit_amount": 0.0,
                "reconciliation_status": "PASS" if abs(rec_delta) <= 1 else "FAIL",
                "reconciliation_delta": rec_delta,
                "extraction_gaps": 0,
                "missing_debit_amount": max(rec_delta, 0),
                "missing_credit_amount": abs(min(rec_delta, 0)),
                "own_party_cr_count": 0,
                "own_party_dr_count": 0,
                "related_party_cr_count": 0,
                "related_party_dr_count": 0,
                "loan_repayment_count": 0,
                "inward_return_cr": 0.0,
                "unclassified_cr_count": 0,
                "unclassified_cr_amount": 0.0,
                "unclassified_dr_count": 0,
                "unclassified_dr_amount": 0.0,
            }
        )

    monthly_index = {(m["month"], m["account_number"], m["bank_name"]): m for m in monthly_analysis}

    gross_credits = round(float(sum(x["gross_credits"] for x in monthly_analysis)), 2)
    gross_debits = round(float(sum(x["gross_debits"] for x in monthly_analysis)), 2)

    checks = []
    for m in monthly_analysis:
        checks.append(
            {
                "month": m["month"],
                "account_number": m["account_number"],
                "bank_name": m["bank_name"],
                "opening_balance": m["opening_balance"],
                "closing_balance": m["closing_balance"],
                "gross_credits": m["gross_credits"],
                "gross_debits": m["gross_debits"],
                "expected_closing": round(m["opening_balance"] + m["gross_credits"] - m["gross_debits"], 2),
                "reconciliation_delta": m["reconciliation_delta"],
                "passed": abs(float(m["reconciliation_delta"])) <= 1,
                "transactions_extracted": 0,
                "notes": "",
            }
        )

    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    success_rate = round((passed / total) * 100, 2) if total else 100.0

    high_value = []
    if not df.empty:
        if "rule_category_code" in df.columns:
            high_value_src = df[df["rule_category_code"].fillna("").astype(str).str.upper() == "C23"]
        else:
            high_value_src = df[df.get("credit", pd.Series([], dtype=float)).apply(safe_float) >= 100000]
        for _, row in high_value_src.iterrows():
            high_value.append(
                {
                    "date": _as_date(row.get("date")),
                    "description": str(row.get("description") or ""),
                    "amount": round(float(safe_float(row.get("credit"))), 2),
                    "category": str(row.get("rule_category_code") or "C23"),
                    "balance": round(float(safe_float(row.get("balance"))), 2),
                }
            )

    unclassified = []
    if not df.empty:
        for _, row in df.iterrows():
            amount, tx_side = _tx_amount_and_side(row)
            if not tx_side:
                continue

            month = _as_month(row.get("date"))
            account_no = str(row.get("account_no") or "Unknown Account")
            bank_name = str(row.get("bank") or bank_by_account.get(account_no) or "Unknown Bank")
            month_rec = monthly_index.get((month, account_no, bank_name))
            if month_rec is None:
                continue

            if tx_side == "CR":
                month_rec["credit_count"] += 1
            else:
                month_rec["debit_count"] += 1

            category_code = str(row.get("rule_category_code") or "").strip().upper()
            if _apply_category_to_month(month_rec, category_code, amount):
                continue

            if tx_side == "CR":
                month_rec["unclassified_cr_count"] += 1
                month_rec["unclassified_cr_amount"] += amount
                tx_type = "CREDIT"
            else:
                month_rec["unclassified_dr_count"] += 1
                month_rec["unclassified_dr_amount"] += amount
                tx_type = "DEBIT"
            unclassified.append(
                {
                    "date": _as_date(row.get("date")),
                    "description": str(row.get("description") or ""),
                    "amount": round(float(amount), 2),
                    "type": tx_type,
                    "account_number": str(row.get("account_no") or "Unknown Account"),
                    "bank_name": str(row.get("bank") or "Unknown Bank"),
                    "reason": "No matching classification rule",
                }
            )

    monthly_float_fields = [
        "own_party_cr",
        "own_party_dr",
        "related_party_cr",
        "related_party_dr",
        "reversal_cr",
        "returned_cheques_inward_amount",
        "returned_cheques_outward_amount",
        "loan_disbursement_cr",
        "fd_interest_cr",
        "round_figure_cr",
        "high_value_cr",
        "cash_deposits_amount",
        "cash_withdrawals_amount",
        "cheque_deposits_amount",
        "cheque_issues_amount",
        "loan_repayment_dr",
        "salary_paid",
        "statutory_epf",
        "statutory_socso",
        "statutory_tax",
        "statutory_hrdf",
        "inward_return_cr",
        "unclassified_cr_amount",
        "unclassified_dr_amount",
    ]
    for m in monthly_analysis:
        for field_name in monthly_float_fields:
            m[field_name] = round(float(safe_float(m.get(field_name, 0))), 2)

    report = {
        "report_info": {
            "schema_version": schema_version,
            "company_name": company_name,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "period_start": date_min,
            "period_end": date_max,
            "total_accounts": len(accounts),
            "total_months": len(monthly_analysis),
            "related_parties": [],
        },
        "accounts": accounts,
        "monthly_analysis": monthly_analysis,
        "consolidated": {
            "gross_credits": gross_credits,
            "gross_debits": gross_debits,
            "net_credits": round(max(gross_credits - gross_debits, 0), 2),
            "net_debits": round(max(gross_debits - gross_credits, 0), 2),
            "annualized_net_credits": round(max(gross_credits - gross_debits, 0) * 12, 2),
            "annualized_net_debits": round(max(gross_debits - gross_credits, 0) * 12, 2),
            "total_own_party_cr": round(float(sum(x["own_party_cr"] for x in monthly_analysis)), 2),
            "total_own_party_dr": round(float(sum(x["own_party_dr"] for x in monthly_analysis)), 2),
            "total_related_party_cr": round(float(sum(x["related_party_cr"] for x in monthly_analysis)), 2),
            "total_related_party_dr": round(float(sum(x["related_party_dr"] for x in monthly_analysis)), 2),
            "total_reversal_cr": round(float(sum(x["reversal_cr"] for x in monthly_analysis)), 2),
            "total_returned_cheques_inward": round(float(sum(x["returned_cheques_inward_amount"] for x in monthly_analysis)), 2),
            "total_returned_cheques_outward": round(float(sum(x["returned_cheques_outward_amount"] for x in monthly_analysis)), 2),
            "total_loan_disbursement_cr": round(float(sum(x["loan_disbursement_cr"] for x in monthly_analysis)), 2),
            "total_fd_interest_cr": round(float(sum(x["fd_interest_cr"] for x in monthly_analysis)), 2),
            "total_round_figure_cr": round(float(sum(x["round_figure_cr"] for x in monthly_analysis)), 2),
            "total_high_value_cr": round(float(sum(x["amount"] for x in high_value)), 2),
            "total_cash_deposits": round(float(sum(x["cash_deposits_amount"] for x in monthly_analysis)), 2),
            "total_cash_withdrawals": round(float(sum(x["cash_withdrawals_amount"] for x in monthly_analysis)), 2),
            "total_cheque_deposits": round(float(sum(x["cheque_deposits_amount"] for x in monthly_analysis)), 2),
            "total_cheque_issues": round(float(sum(x["cheque_issues_amount"] for x in monthly_analysis)), 2),
            "total_loan_repayment_dr": round(float(sum(x["loan_repayment_dr"] for x in monthly_analysis)), 2),
            "total_salary_paid": round(float(sum(x["salary_paid"] for x in monthly_analysis)), 2),
            "total_statutory_epf": round(float(sum(x["statutory_epf"] for x in monthly_analysis)), 2),
            "total_statutory_socso": round(float(sum(x["statutory_socso"] for x in monthly_analysis)), 2),
            "total_statutory_tax": round(float(sum(x["statutory_tax"] for x in monthly_analysis)), 2),
            "total_statutory_hrdf": round(float(sum(x["statutory_hrdf"] for x in monthly_analysis)), 2),
            "eod_lowest": round(float(min((x["eod_lowest"] for x in monthly_analysis), default=0.0)), 2),
            "eod_highest": round(float(max((x["eod_highest"] for x in monthly_analysis), default=0.0)), 2),
            "eod_average": round(float(sum((x["eod_average"] for x in monthly_analysis), 0.0) / len(monthly_analysis)), 2)
            if monthly_analysis
            else 0.0,
            "total_fx_credits": round(float(sum(x["fx_credit_amount"] for x in monthly_analysis)), 2),
            "total_fx_debits": round(float(sum(x["fx_debit_amount"] for x in monthly_analysis)), 2),
            "data_completeness": "COMPLETE" if success_rate >= 95 else "INCOMPLETE",
            "months_with_gaps": int(sum(1 for x in monthly_analysis if x["extraction_gaps"] > 0)),
            "total_extraction_gaps": int(sum(x["extraction_gaps"] for x in monthly_analysis)),
            "total_missing_debits": round(float(sum(x["missing_debit_amount"] for x in monthly_analysis)), 2),
            "total_missing_credits": round(float(sum(x["missing_credit_amount"] for x in monthly_analysis)), 2),
            "total_inward_return_cr": round(float(sum(x["inward_return_cr"] for x in monthly_analysis)), 2),
            "total_unclassified_cr": round(float(sum(x["unclassified_cr_amount"] for x in monthly_analysis)), 2),
            "total_unclassified_dr": round(float(sum(x["unclassified_dr_amount"] for x in monthly_analysis)), 2),
        },
        "top_parties": {
            "top_payers": _party_rows(df, "credit", top_n=5) if not df.empty and "credit" in df.columns else [],
            "top_payees": _party_rows(df, "debit", top_n=5) if not df.empty and "debit" in df.columns else [],
        },
        "large_credits": high_value,
        "own_related_transactions": {
            "summary": {
                "own_party_cr": round(float(sum(x["own_party_cr"] for x in monthly_analysis)), 2),
                "own_party_dr": round(float(sum(x["own_party_dr"] for x in monthly_analysis)), 2),
                "related_party_cr": round(float(sum(x["related_party_cr"] for x in monthly_analysis)), 2),
                "related_party_dr": round(float(sum(x["related_party_dr"] for x in monthly_analysis)), 2),
                "own_party_cr_pct": round((sum(x["own_party_cr"] for x in monthly_analysis) / gross_credits * 100), 2) if gross_credits else 0.0,
                "own_party_dr_pct": round((sum(x["own_party_dr"] for x in monthly_analysis) / gross_debits * 100), 2) if gross_debits else 0.0,
                "related_party_cr_pct": round((sum(x["related_party_cr"] for x in monthly_analysis) / gross_credits * 100), 2) if gross_credits else 0.0,
                "related_party_dr_pct": round((sum(x["related_party_dr"] for x in monthly_analysis) / gross_debits * 100), 2) if gross_debits else 0.0,
            },
            "transactions": [],
        },
        "loan_transactions": {"disbursements": [], "repayments": []},
        "flags": {"indicators": []},
        "observations": {"positive": [], "concerns": []},
        "parsing_metadata": {
            "overall_success_rate": success_rate,
            "total_transactions_extracted": int(len(df)),
            "total_balance_checks": total,
            "total_balance_checks_passed": passed,
            "account_month_checks": checks,
            "extraction_gaps": None,
        },
        "unclassified_transactions": unclassified,
        "classification_config": {
            "rulebook_version": "3.0.0",
            "large_credit_threshold": 100000,
            "unclassified_listing_threshold": 10000,
            "known_factoring_entities": [],
            "execution_mode": "FULL_CODE" if apply_rules_v3 else "OPTIMISED_AI",
        },
        "_internal": {
            "rules": rules_metadata,
            "rules_applied_to_transactions": apply_rules_v3,
            "transactions": transactions,
            "monthly_summary": monthly_summary,
        },
    }
    return report


def validate_schema_report(report: Dict[str, Any]) -> List[str]:
    schema = _load_schema()
    if not schema:
        return ["Schema file could not be loaded"]

    try:
        from jsonschema import Draft202012Validator
    except Exception:
        return ["jsonschema package not installed; validation skipped"]

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(report), key=lambda e: list(e.path))
    out: List[str] = []
    for e in errors[:20]:
        path = ".".join(str(p) for p in e.path)
        out.append(f"{path}: {e.message}")
    return out
