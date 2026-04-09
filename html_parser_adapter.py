from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd


def build_analysis_payload(
    *,
    df: pd.DataFrame,
    monthly_summary: List[dict],
    bank_choice: str,
    total_files_processed: Optional[int],
    date_min: Optional[str],
    date_max: Optional[str],
) -> Dict[str, Any]:
    """Map current app output into a HTML-parser friendly schema.

    This adapter keeps existing parser flow unchanged and only builds a final-layer
    report payload for HTML rendering.
    """
    company_names = sorted({str(x).strip() for x in df.get("company_name", pd.Series([], dtype=object)).dropna() if str(x).strip()})
    account_nos = sorted({str(x).strip() for x in df.get("account_no", pd.Series([], dtype=object)).dropna() if str(x).strip()})

    total_credit = float(df.get("credit", pd.Series([], dtype=float)).fillna(0).sum()) if not df.empty else 0.0
    total_debit = float(df.get("debit", pd.Series([], dtype=float)).fillna(0).sum()) if not df.empty else 0.0

    monthly_rows: List[Dict[str, Any]] = []
    for row in monthly_summary or []:
        monthly_rows.append(
            {
                "month": row.get("month"),
                "account_number": row.get("account_no"),
                "bank_name": bank_choice,
                "opening_balance": row.get("opening_balance", 0) or 0,
                "closing_balance": row.get("ending_balance", 0) or 0,
                "gross_credits": row.get("total_credit", 0) or 0,
                "gross_debits": row.get("total_debit", 0) or 0,
                "net_credits": row.get("total_credit", 0) or 0,
                "net_debits": row.get("total_debit", 0) or 0,
                "eod_lowest": row.get("lowest_balance", 0) or 0,
                "eod_highest": row.get("highest_balance", 0) or 0,
                "eod_average": ((row.get("lowest_balance", 0) or 0) + (row.get("highest_balance", 0) or 0)) / 2,
                "credit_count": 0,
                "debit_count": 0,
            }
        )

    accounts = []
    for acct in account_nos or [""]:
        acct_df = df[df.get("account_no", pd.Series([], dtype=object)).astype(str) == acct] if acct else df
        accounts.append(
            {
                "bank_name": bank_choice,
                "account_number": acct,
                "account_holder": company_names[0] if company_names else "",
                "account_type": "Current",
                "opening_balance": float(acct_df.get("balance", pd.Series([], dtype=float)).dropna().iloc[0]) if not acct_df.empty and acct_df.get("balance", pd.Series([], dtype=float)).dropna().any() else 0,
                "closing_balance": float(acct_df.get("balance", pd.Series([], dtype=float)).dropna().iloc[-1]) if not acct_df.empty and acct_df.get("balance", pd.Series([], dtype=float)).dropna().any() else 0,
                "total_credits": float(acct_df.get("credit", pd.Series([], dtype=float)).fillna(0).sum()) if not acct_df.empty else 0,
                "total_debits": float(acct_df.get("debit", pd.Series([], dtype=float)).fillna(0).sum()) if not acct_df.empty else 0,
                "transaction_count": int(len(acct_df)),
            }
        )

    return {
        "report_info": {
            "schema_version": "6.3.0",
            "company_name": company_names[0] if company_names else "Unknown",
            "period_start": date_min,
            "period_end": date_max,
            "total_months": len({x.get("month") for x in monthly_summary if x.get("month")}),
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "bank-statement-parser",
        },
        "accounts": accounts,
        "monthly_analysis": monthly_rows,
        "consolidated": {
            "net_credits": total_credit,
            "net_debits": total_debit,
            "gross_credits": total_credit,
            "gross_debits": total_debit,
            "annualized_net_credits": total_credit * 12,
            "annualized_net_debits": total_debit * 12,
            "eod_average": float(df.get("balance", pd.Series([], dtype=float)).fillna(0).mean()) if not df.empty else 0,
            "eod_lowest": float(df.get("balance", pd.Series([], dtype=float)).min()) if not df.empty else 0,
            "eod_highest": float(df.get("balance", pd.Series([], dtype=float)).max()) if not df.empty else 0,
            "total_files_processed": int(total_files_processed or 0),
            "total_unclassified_cr": 0,
            "total_unclassified_dr": 0,
        },
        "flags": {"indicators": []},
        "observations": {"positive": [], "concerns": []},
        "transactions": df.to_dict(orient="records"),
    }


def generate_interactive_html(data: Dict[str, Any]) -> str:
    """Generate a lightweight interactive HTML report from analysis payload."""
    report = data.get("report_info", {})
    accounts = data.get("accounts", [])
    monthly = data.get("monthly_analysis", [])
    consol = data.get("consolidated", {})

    rows = "".join(
        f"<tr><td>{html.escape(str(m.get('month','')))}</td><td>{html.escape(str(m.get('account_number','')))}</td>"
        f"<td style='text-align:right'>{(m.get('gross_credits',0) or 0):,.2f}</td>"
        f"<td style='text-align:right'>{(m.get('gross_debits',0) or 0):,.2f}</td>"
        f"<td style='text-align:right'>{(m.get('closing_balance',0) or 0):,.2f}</td></tr>"
        for m in monthly
    )

    account_cards = "".join(
        f"<div class='card'><h4>{html.escape(str(a.get('bank_name','')))} - {html.escape(str(a.get('account_number','')))}</h4>"
        f"<p>Holder: {html.escape(str(a.get('account_holder','')))}</p>"
        f"<p>Credits: RM {(a.get('total_credits',0) or 0):,.2f}</p>"
        f"<p>Debits: RM {(a.get('total_debits',0) or 0):,.2f}</p>"
        f"<p>Closing: RM {(a.get('closing_balance',0) or 0):,.2f}</p></div>"
        for a in accounts
    )

    chart_months = json.dumps([m.get("month", "") for m in monthly])
    chart_credits = json.dumps([round(float(m.get("gross_credits", 0) or 0), 2) for m in monthly])
    chart_debits = json.dumps([round(float(m.get("gross_debits", 0) or 0), 2) for m in monthly])

    return f"""<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Statement Intelligence Report</title>
<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>
<style>
body{{font-family:Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:0;padding:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px}}
table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{border:1px solid #e2e8f0;padding:8px}}th{{background:#0f172a;color:#fff}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:12px 0}}
</style>
</head>
<body>
<h2>🔬 Statement Intelligence Report</h2>
<p><b>Company:</b> {html.escape(str(report.get('company_name','Unknown')))}<br>
<b>Period:</b> {html.escape(str(report.get('period_start','')))} to {html.escape(str(report.get('period_end','')))}<br>
<b>Schema:</b> {html.escape(str(report.get('schema_version','')))}</p>

<div class='kpis'>
<div class='card'><b>Net Credits</b><div>RM {(consol.get('net_credits',0) or 0):,.2f}</div></div>
<div class='card'><b>Net Debits</b><div>RM {(consol.get('net_debits',0) or 0):,.2f}</div></div>
<div class='card'><b>EOD Avg</b><div>RM {(consol.get('eod_average',0) or 0):,.2f}</div></div>
<div class='card'><b>Files</b><div>{int(consol.get('total_files_processed',0) or 0)}</div></div>
</div>

<h3>Accounts</h3>
<div class='grid'>{account_cards}</div>

<h3>Monthly Performance</h3>
<div id='chart' style='height:360px'></div>
<script>
Plotly.newPlot('chart',[
{{x:{chart_months},y:{chart_credits},type:'bar',name:'Credits'}},
{{x:{chart_months},y:{chart_debits},type:'bar',name:'Debits'}}
],{{barmode:'group',margin:{{t:20}}}})
</script>

<h3>Monthly Table</h3>
<table>
<thead><tr><th>Month</th><th>Account</th><th>Credits</th><th>Debits</th><th>Closing Balance</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
