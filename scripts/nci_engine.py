#!/usr/bin/env python3
"""
Reference implementation of the NCI monitoring/reporting logic.

This is the business logic that the Power Automate flows will replicate
using their own actions (HTTP, Filter array, Select, Compose, Send email).
Keeping it here first lets us prove the filtering/aggregation rules are
correct against real data before wiring up connectors in a tenant we don't
have direct access to.

Usage:
    python3 nci_engine.py query --status Open --department Cloud
    python3 nci_engine.py query --account Contoso
    python3 nci_engine.py report --period weekly
"""
import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "sample_nci_data.csv"
TRACKER_FILE = ROOT / "config" / "tracker.csv"

TODAY = date(2026, 8, 29)  # swap for date.today() once wired to a live source


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def load_ncis(path: Path = DATA_FILE) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["created_date"] = parse_date(r["created_date"])
        r["due_date"] = parse_date(r["due_date"])
        r["extension_count"] = int(r["extension_count"])
        r["age_days"] = (TODAY - r["created_date"]).days
        r["days_to_due"] = (r["due_date"] - TODAY).days
        r["is_overdue"] = r["status"] == "Open" and r["days_to_due"] < 0
        r["is_due_in_7_days"] = r["status"] == "Open" and 0 <= r["days_to_due"] <= 7
        r["is_excessive_extension"] = r["extension_count"] > 2
        r["is_aged_over_1yr"] = r["status"] == "Open" and r["age_days"] > 365
    return rows


def load_tracker(path: Path = TRACKER_FILE) -> dict[str, dict]:
    with open(path, newline="") as f:
        return {row["account"]: row for row in csv.DictReader(f)}


def filter_ncis(rows, account=None, region=None, department=None, status=None):
    out = rows
    if account:
        out = [r for r in out if r["account"].lower() == account.lower()]
    if region:
        out = [r for r in out if r["region"].lower() == region.lower()]
    if department:
        out = [r for r in out if r["department"].lower() == department.lower()]
    if status:
        out = [r for r in out if r["status"].lower() == status.lower()]
    return out


def compute_scorecard(rows) -> dict:
    open_rows = [r for r in rows if r["status"] == "Open"]
    total_open = len(open_rows) or 1  # avoid div/0 in the sample set
    overdue = [r for r in open_rows if r["is_overdue"]]
    due_soon = [r for r in open_rows if r["is_due_in_7_days"]]
    excessive_ext = [r for r in open_rows if r["is_excessive_extension"]]
    aged = [r for r in open_rows if r["is_aged_over_1yr"]]
    return {
        "total_open": len(open_rows),
        "overdue_count": len(overdue),
        "overdue_pct": round(100 * len(overdue) / total_open, 1),
        "due_in_7_days_count": len(due_soon),
        "due_in_7_days_pct": round(100 * len(due_soon) / total_open, 1),
        "excessive_extension_count": len(excessive_ext),
        "excessive_extension_pct": round(100 * len(excessive_ext) / total_open, 1),
        "aged_over_1yr": aged,
    }


def render_table(rows: list[dict]) -> str:
    cols = ["nci_id", "account", "region", "department", "severity", "status", "due_date", "extension_count"]
    header = " | ".join(cols)
    sep = "-" * len(header)
    lines = [header, sep]
    for r in rows:
        lines.append(" | ".join(str(r[c]) for c in cols))
    return "\n".join(lines)


def render_report(rows: list[dict], period: str) -> str:
    scorecard = compute_scorecard(rows)
    lines = [f"NCI Scorecard — {period} — as of {TODAY.isoformat()}", "=" * 60]
    by_account: dict[str, list[dict]] = {}
    for r in rows:
        by_account.setdefault(r["account"], []).append(r)

    lines.append(
        f"Total open: {scorecard['total_open']} | "
        f"Overdue: {scorecard['overdue_count']} ({scorecard['overdue_pct']}%) | "
        f"Due in 7 days: {scorecard['due_in_7_days_count']} ({scorecard['due_in_7_days_pct']}%) | "
        f"Excessive extensions (>2): {scorecard['excessive_extension_count']} ({scorecard['excessive_extension_pct']}%)"
    )
    if scorecard["aged_over_1yr"]:
        aged_ids = ", ".join(r["nci_id"] for r in scorecard["aged_over_1yr"])
        lines.append(f"NCIs open > 1 year (priority): {aged_ids}")
    lines.append("")

    for account, acct_rows in sorted(by_account.items()):
        open_acct = [r for r in acct_rows if r["status"] == "Open"]
        lines.append(f"-- {account} ({len(open_acct)} open) --")
        lines.append(render_table(acct_rows))
        lines.append("")
    return "\n".join(lines)


def resolve_recipients(tracker: dict, account: str) -> dict:
    entry = tracker.get(account)
    if not entry:
        return {"to": [], "cc": []}
    return {
        "to": [e.strip() for e in entry["to_emails"].split(";") if e.strip()],
        "cc": [e.strip() for e in entry["cc_emails"].split(";") if e.strip()],
    }


def send_email_stub(to: list[str], cc: list[str], subject: str, body: str):
    """
    Placeholder for the Outlook 'Send an email (V2)' action in Power Automate.
    Prints instead of sending — swap for a real connector once credentials exist.
    """
    print(f"[STUB SEND] To={to} Cc={cc}")
    print(f"Subject: {subject}")
    print(body[:400] + ("..." if len(body) > 400 else ""))


def cmd_query(args):
    rows = load_ncis()
    filtered = filter_ncis(rows, account=args.account, region=args.region,
                            department=args.department, status=args.status or "Open")
    if not filtered:
        print("No matching NCIs.")
        return
    print(render_table(filtered))


def cmd_report(args):
    rows = load_ncis()
    filtered = filter_ncis(rows, account=args.account, region=args.region, department=args.department)
    report_text = render_report(filtered, args.period)
    print(report_text)

    if args.send:
        tracker = load_tracker()
        by_account: dict[str, list[dict]] = {}
        for r in filtered:
            by_account.setdefault(r["account"], []).append(r)
        for account, acct_rows in by_account.items():
            recipients = resolve_recipients(tracker, account)
            if not recipients["to"]:
                print(f"[WARN] No tracker entry for account '{account}', skipping email.")
                continue
            body = render_report(acct_rows, args.period)
            send_email_stub(recipients["to"], recipients["cc"],
                             f"NCI {args.period.title()} Report — {account}", body)


def main():
    parser = argparse.ArgumentParser(description="NCI monitoring/reporting reference engine")
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("query", help="Ask for open NCIs matching filters")
    q.add_argument("--account")
    q.add_argument("--region")
    q.add_argument("--department", help="Cloud or NMS")
    q.add_argument("--status", help="Open/Closed, default Open")
    q.set_defaults(func=cmd_query)

    r = sub.add_parser("report", help="Generate + optionally send the period report")
    r.add_argument("--period", default="weekly")
    r.add_argument("--account")
    r.add_argument("--region")
    r.add_argument("--department")
    r.add_argument("--send", action="store_true", help="Also resolve recipients and stub-send per account")
    r.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
