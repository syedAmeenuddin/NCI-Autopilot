"""
Run with: python3 -m pytest scripts/test_nci_engine.py -v

Locks down the business rules from the process sheet (row 3: overdue %,
excessive extensions >2, due-in-7-days bucket, >1yr aging) against the
sample data, so a future schema change can't silently break the logic.
"""
from nci_engine import (
    load_ncis,
    load_tracker,
    filter_ncis,
    compute_scorecard,
    resolve_recipients,
)


def test_filter_by_account_and_department():
    rows = load_ncis()
    result = filter_ncis(rows, account="Contoso", department="Cloud", status="Open")
    ids = {r["nci_id"] for r in result}
    assert ids == {"NCI-10001", "NCI-10013"}


def test_filter_by_region():
    rows = load_ncis()
    result = filter_ncis(rows, region="APAC", status="Open")
    ids = {r["nci_id"] for r in result}
    assert ids == {"NCI-10001", "NCI-10002", "NCI-10007", "NCI-10008", "NCI-10013"}


def test_filter_excludes_closed_by_default_status():
    rows = load_ncis()
    result = filter_ncis(rows, account="Fabrikam", status="Open")
    ids = {r["nci_id"] for r in result}
    assert "NCI-10004" not in ids  # NCI-10004 is Closed


def test_scorecard_matches_known_values_for_apac():
    rows = load_ncis()
    apac_open = filter_ncis(rows, region="APAC", status="Open")
    scorecard = compute_scorecard(apac_open)
    assert scorecard["total_open"] == 5
    assert scorecard["overdue_count"] == 4
    assert scorecard["overdue_pct"] == 80.0
    assert scorecard["due_in_7_days_count"] == 0
    assert scorecard["excessive_extension_count"] == 0


def test_excessive_extension_flagging():
    rows = load_ncis()
    umbrella = filter_ncis(rows, account="Umbrella", status="Open")
    scorecard = compute_scorecard(umbrella)
    # NCI-10009 has extension_count=4, must be flagged excessive (>2)
    assert scorecard["excessive_extension_count"] == 1


def test_aged_over_1yr_flagging():
    rows = load_ncis()
    # NCI-10009 created 2025-01-15, "today" pinned to 2026-08-29 -> >365 days old, still Open
    umbrella = filter_ncis(rows, account="Umbrella", status="Open")
    scorecard = compute_scorecard(umbrella)
    aged_ids = {r["nci_id"] for r in scorecard["aged_over_1yr"]}
    assert "NCI-10009" in aged_ids


def test_resolve_recipients_known_account():
    tracker = load_tracker()
    recipients = resolve_recipients(tracker, "Contoso")
    assert recipients["to"] == ["contoso.lead@example.com", "contoso.pm@example.com"]
    assert recipients["cc"] == ["issuemgmt.apac@example.com"]


def test_resolve_recipients_unknown_account_returns_empty():
    tracker = load_tracker()
    recipients = resolve_recipients(tracker, "NoSuchAccount")
    assert recipients == {"to": [], "cc": []}
