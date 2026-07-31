"""
Analytics pages.

System Analytics: totals, per-camera breakdown, top-5 by ABSOLUTE weight diff.
Accuracy: the dynamic accuracy metric - every rule pinned down explicitly,
since this is the most business-critical calculation in the app.
"""

import re

import pytest


# =====================================================================
# System Analytics
# =====================================================================

def test_default_range_is_today_only(client, insert_activity, today, yesterday):
    insert_activity(activity_number=1, order_number="ORD01", date=today)
    insert_activity(activity_number=2, order_number="ORD02", date=yesterday)

    body = client.get("/analytics/system").data.decode()
    assert "ORD01" in body
    assert "ORD02" not in body


def test_result_totals(client, insert_activity, today):
    insert_activity(activity_number=1, validation_result="PASS", date=today)
    insert_activity(activity_number=2, validation_result="PASS", date=today)
    insert_activity(activity_number=3, validation_result="FAIL", date=today)
    insert_activity(activity_number=4, validation_result="MISSING_DATA", date=today)

    body = client.get("/analytics/system").data.decode()
    assert "Total Activities" in body
    # 2 of 4 = 50.0% pass
    assert "50.0%" in body


def test_per_camera_breakdown_is_independent_per_camera(client, insert_activity, today):
    # camera_4: 2 PASS, 1 FAIL  |  camera_5: 1 FAIL
    insert_activity(activity_number=1, camera_name="camera_4", validation_result="PASS", date=today)
    insert_activity(activity_number=2, camera_name="camera_4", validation_result="PASS", date=today)
    insert_activity(activity_number=3, camera_name="camera_4", validation_result="FAIL", date=today)
    insert_activity(activity_number=4, camera_name="camera_5", validation_result="FAIL", date=today)

    body = client.get("/analytics/system").data.decode()
    assert "camera_4" in body and "camera_5" in body
    assert "3 total" in body   # camera_4
    assert "1 total" in body   # camera_5
    assert "66.7%" in body     # camera_4 pass rate, relative to its OWN total
    assert "stacked-bar__seg--pass" in body
    assert "stacked-bar__seg--fail" in body


def test_top_five_ranks_by_absolute_difference_not_percentage(client, insert_activity, today):
    """
    Regression: this used to rank by weight_difference_percent. A small item
    can have a huge percentage but a tiny absolute difference - ranking must
    use the absolute value.
    """
    # Big percentage, tiny absolute difference
    insert_activity(
        activity_number=1, order_number="ORD_SMALL", date=today,
        weight_difference="0.5", weight_difference_percent="500.0%",
    )
    # Small percentage, huge absolute difference
    insert_activity(
        activity_number=2, order_number="ORD_BIG", date=today,
        weight_difference="50.0", weight_difference_percent="5.0%",
    )

    body = client.get("/analytics/system").data.decode()
    assert body.index("ORD_BIG") < body.index("ORD_SMALL")


def test_top_five_caps_at_five_rows(client, insert_activity, today):
    for n in range(1, 9):
        insert_activity(
            activity_number=n, order_number=f"ORD{n:02d}", date=today,
            weight_difference=str(n), weight_difference_percent=f"{n}.0%",
        )
    body = client.get("/analytics/system").data.decode()
    assert "Top 5" in body
    assert body.count("View Details") == 5


def test_negative_differences_ranked_by_magnitude(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD_NEG", date=today, weight_difference="-40.0")
    insert_activity(activity_number=2, order_number="ORD_POS", date=today, weight_difference="5.0")

    body = client.get("/analytics/system").data.decode()
    assert body.index("ORD_NEG") < body.index("ORD_POS")


def test_non_numeric_difference_is_skipped_not_crashed(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD_BAD", date=today, weight_difference="None")
    insert_activity(activity_number=2, order_number="ORD_OK", date=today, weight_difference="3.0")

    resp = client.get("/analytics/system")
    assert resp.status_code == 200
    assert "ORD_OK" in resp.data.decode()


def test_empty_state(client):
    assert "No activity records" in client.get("/analytics/system").data.decode()


# =====================================================================
# Accuracy Analytics
# =====================================================================
#
# Rules under test:
#   - PASS                                     -> correct (never needs review)
#   - FAIL/MISSING_DATA, nothing marked        -> EXCLUDED entirely
#   - FAIL/MISSING_DATA, System Error = YES    -> incorrect
#   - FAIL/MISSING_DATA, System Error = NO     -> correct
#   - FAIL/MISSING_DATA, Process Error = YES   -> correct
#   - both marked YES                          -> incorrect (System Error wins)
#
#   accuracy = (PASS + correct non-pass) / (PASS + reviewed non-pass) * 100

def test_defaults_to_yesterday(client, insert_activity, today, yesterday):
    insert_activity(activity_number=1, order_number="ORD_YEST", date=yesterday)
    insert_activity(activity_number=2, order_number="ORD_TODAY", date=today)

    body = client.get("/analytics/accuracy").data.decode()
    assert "ORD_YEST" not in body or "Total Activities" in body  # page rendered
    # The date input should default to yesterday
    assert f'value="{yesterday.isoformat()}"' in body


def test_all_pass_is_one_hundred_percent(client, insert_activity, yesterday):
    for n in range(1, 4):
        insert_activity(activity_number=n, validation_result="PASS", date=yesterday)

    body = client.get("/analytics/accuracy").data.decode()
    assert "100.0%" in body


def test_unreviewed_failures_are_excluded_not_counted_wrong(client, insert_activity, yesterday):
    """3 PASS + 2 completely unreviewed FAIL -> still 100%, with 2 excluded."""
    for n in range(1, 4):
        insert_activity(activity_number=n, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=4, validation_result="FAIL", date=yesterday)
    insert_activity(activity_number=5, validation_result="MISSING_DATA", date=yesterday)

    body = client.get("/analytics/accuracy").data.decode()
    assert "100.0%" in body
    assert "2 activities are excluded" in body


def test_system_error_yes_counts_as_incorrect(client, insert_activity, yesterday):
    """1 PASS + 1 FAIL marked System Error -> 1/2 = 50%."""
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="FAIL", date=yesterday, mark_ocr_wrong="YES")

    assert "50.0%" in client.get("/analytics/accuracy").data.decode()


def test_system_error_no_counts_as_correct(client, insert_activity, yesterday):
    """1 PASS + 1 FAIL marked System Error = NO -> both correct -> 100%."""
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="FAIL", date=yesterday, mark_ocr_wrong="NO")

    assert "100.0%" in client.get("/analytics/accuracy").data.decode()


def test_process_error_yes_counts_as_correct(client, insert_activity, yesterday):
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="FAIL", date=yesterday, mark_process_error="YES")

    assert "100.0%" in client.get("/analytics/accuracy").data.decode()


def test_both_marked_yes_system_error_takes_priority(client, insert_activity, yesterday):
    """Documented edge case: System Error wins, so this counts as incorrect."""
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(
        activity_number=2, validation_result="FAIL", date=yesterday,
        mark_ocr_wrong="YES", mark_process_error="YES",
    )
    assert "50.0%" in client.get("/analytics/accuracy").data.decode()


def test_process_error_only_marked_no_counts_as_correct(client, insert_activity, yesterday):
    """
    System Error untouched but Process Error marked NO: the activity IS
    reviewed (something was marked), and only an explicit System Error = YES
    makes it incorrect - so this is correct.
    """
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="FAIL", date=yesterday, mark_process_error="NO")

    assert "100.0%" in client.get("/analytics/accuracy").data.decode()


def test_full_mixed_scenario(client, insert_activity, yesterday):
    """
    The canonical end-to-end scenario, hand-calculated:
      3 PASS                                  -> correct
      1 FAIL   System Error=YES               -> incorrect
      1 FAIL   Process Error=YES              -> correct
      1 MISSING both marked NO                -> correct
      1 FAIL   unmarked                       -> excluded
      1 MISSING unmarked                      -> excluded
      1 FAIL   both YES (System Error wins)   -> incorrect

      reviewed non-pass = 4, correct non-pass = 2, excluded = 2
      accuracy = (3 + 2) / (3 + 4) * 100 = 5/7 = 71.4%
    """
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=3, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=4, validation_result="FAIL", date=yesterday, mark_ocr_wrong="YES")
    insert_activity(activity_number=5, validation_result="FAIL", date=yesterday, mark_process_error="YES")
    insert_activity(
        activity_number=6, validation_result="MISSING_DATA", date=yesterday,
        mark_ocr_wrong="NO", mark_process_error="NO",
    )
    insert_activity(activity_number=7, validation_result="FAIL", date=yesterday)
    insert_activity(activity_number=8, validation_result="MISSING_DATA", date=yesterday)
    insert_activity(
        activity_number=9, validation_result="FAIL", date=yesterday,
        mark_ocr_wrong="YES", mark_process_error="YES",
    )

    body = client.get("/analytics/accuracy").data.decode()
    assert "71.4%" in body
    assert "2 activities are excluded" in body


def test_no_reviewed_data_shows_not_available(client, insert_activity, yesterday):
    """Only unreviewed failures -> accuracy is genuinely unknown, not 0%."""
    insert_activity(activity_number=1, validation_result="FAIL", date=yesterday)

    body = client.get("/analytics/accuracy").data.decode()
    assert "N/A" in body
    assert "No reviewed data yet" in body
    assert "0.0%" not in body


def test_flowchart_structure_is_rendered(client, insert_activity, yesterday):
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="FAIL", date=yesterday, mark_ocr_wrong="YES")

    body = client.get("/analytics/accuracy").data.decode()
    for node in ["flow-node--total", "flow-node--pass", "flow-node--fail",
                 "flow-node--excluded", "flow-node--total-correct"]:
        assert node in body
    assert "Total Correct" in body
    assert "Total Evaluated" in body


def test_formula_substitutes_real_numbers(client, insert_activity, yesterday):
    """The page must show the actual arithmetic, not just the final answer."""
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="FAIL", date=yesterday, mark_ocr_wrong="YES")

    body = client.get("/analytics/accuracy").data.decode()
    assert "1 + 1" in body  # PASS(1) + reviewed(1) = Total Evaluated
    assert "accuracy-formula" in body


def test_singular_wording_for_one_excluded(client, insert_activity, yesterday):
    insert_activity(activity_number=1, validation_result="PASS", date=yesterday)
    insert_activity(activity_number=2, validation_result="FAIL", date=yesterday)

    body = client.get("/analytics/accuracy").data.decode()
    assert "1 activity is excluded" in body


def test_explicit_date_overrides_default(client, insert_activity, today):
    insert_activity(activity_number=1, validation_result="PASS", date=today)
    body = client.get(f"/analytics/accuracy?date={today.isoformat()}").data.decode()
    assert "100.0%" in body


def test_invalid_date_falls_back_gracefully(client):
    assert client.get("/analytics/accuracy?date=garbage").status_code == 200


def test_accuracy_empty_state(client):
    assert "No activity records" in client.get("/analytics/accuracy").data.decode()


# --- Cross-page ---

def test_both_analytics_pages_link_to_each_other(client):
    for route in ["/analytics/system", "/analytics/accuracy"]:
        body = client.get(route).data.decode()
        assert "System Analytics" in body
        assert "Accuracy" in body
        assert "subnav__link is-active" in body
