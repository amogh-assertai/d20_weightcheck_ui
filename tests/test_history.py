"""
History page: filters, search, sorting, pagination, and the Flags column.
"""

import re

import pytest


def _order_numbers_in_order(body):
    """Order numbers as they appear in the rendered table, top to bottom."""
    return re.findall(r"ORD\d+", _table_body(body))


def _table_body(body):
    """
    Just the <tbody> of the results table.

    Assertions must run against this, not the whole page: the filter form
    echoes the active search term back into its input's value=, so a term
    like "ORD01" appears in the raw HTML even when zero rows matched.
    """
    match = re.search(r"<tbody>(.*?)</tbody>", body, re.DOTALL)
    return match.group(1) if match else ""


# --- Date range (default = today only) ---

def test_default_range_is_today_only(client, insert_activity, today, yesterday):
    insert_activity(activity_number=1, order_number="ORD01", date=today)
    insert_activity(activity_number=2, order_number="ORD02", date=yesterday)

    body = client.get("/history").data.decode()
    assert "ORD01" in body
    assert "ORD02" not in body


def test_explicit_date_range_includes_older_records(client, insert_activity, today, yesterday):
    insert_activity(activity_number=2, order_number="ORD02", date=yesterday)
    body = client.get(
        f"/history?start_date={yesterday.isoformat()}&end_date={today.isoformat()}"
    ).data.decode()
    assert "ORD02" in body


def test_invalid_date_falls_back_to_default(client, insert_activity, today):
    insert_activity(order_number="ORD01", date=today)
    resp = client.get("/history?start_date=not-a-date&end_date=also-bad")
    assert resp.status_code == 200
    assert "ORD01" in resp.data.decode()


# --- Filters ---

def test_table_filter(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", camera_name="camera_4", date=today)
    insert_activity(activity_number=2, order_number="ORD02", camera_name="camera_5", date=today)

    body = client.get("/history?table=camera_4").data.decode()
    assert "ORD01" in body and "ORD02" not in body


def test_result_filter(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", validation_result="PASS", date=today)
    insert_activity(activity_number=2, order_number="ORD02", validation_result="FAIL", date=today)

    body = client.get("/history?result=FAIL").data.decode()
    assert "ORD02" in body and "ORD01" not in body


def test_missing_data_is_a_filterable_result(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", validation_result="MISSING_DATA", date=today)
    insert_activity(activity_number=2, order_number="ORD02", validation_result="PASS", date=today)

    body = client.get("/history?result=MISSING_DATA").data.decode()
    assert "ORD01" in body and "ORD02" not in body


@pytest.mark.parametrize(
    "param,field,value",
    [
        ("discuss", "mark_discuss", "YES"),
        ("ocr_wrong", "mark_ocr_wrong", "YES"),
    ],
)
def test_review_flag_filters_yes(client, insert_activity, today, param, field, value):
    insert_activity(activity_number=1, order_number="ORD01", date=today, **{field: value})
    insert_activity(activity_number=2, order_number="ORD02", date=today)

    body = client.get(f"/history?{param}=YES").data.decode()
    assert "ORD01" in body and "ORD02" not in body


def test_review_flag_filter_no_is_distinct_from_unmarked(client, insert_activity, today):
    """Explicit "NO" must be filterable separately from never-touched."""
    insert_activity(activity_number=1, order_number="ORD01", date=today, mark_discuss="NO")
    insert_activity(activity_number=2, order_number="ORD02", date=today)  # untouched

    body = client.get("/history?discuss=NO").data.decode()
    assert "ORD01" in body and "ORD02" not in body


def test_comment_present_filter(client, insert_activity, today):
    """
    Note: present-mode uses the reduced column layout, which deliberately
    drops Order # - so this asserts on the comment text and activity number,
    which are the fields actually rendered in that view.
    """
    insert_activity(activity_number=1, order_number="ORD01", date=today,
                    review_comment="COMMENT_MARKER_ONE")
    insert_activity(activity_number=2, order_number="ORD02", date=today)

    rows = _table_body(client.get("/history?has_comment=present").data.decode())
    assert "COMMENT_MARKER_ONE" in rows
    assert rows.count("View Details") == 1, "only the commented record should be listed"


def test_comment_absent_filter(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", date=today, review_comment="a comment")
    insert_activity(activity_number=2, order_number="ORD02", date=today)

    rows = _table_body(client.get("/history?has_comment=absent").data.decode())
    assert "ORD02" in rows
    assert "ORD01" not in rows


def test_comment_present_switches_to_reduced_column_layout(client, insert_activity, today):
    """With the comment filter on, the table drops columns to make room for full comment text."""
    long_comment = "Label was covered by tape, so OCR could not read the order number."
    insert_activity(activity_number=1, order_number="ORD01", date=today, review_comment=long_comment)

    body = client.get("/history?has_comment=present").data.decode()
    assert "comment-cell-wide" in body
    assert long_comment in body      # full text, untruncated
    assert "<th>Order #</th>" not in body  # dropped column
    assert "Flags" not in body             # dropped column


# --- Search (applies on top of filters) ---

def test_search_by_order_number(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", date=today)
    insert_activity(activity_number=2, order_number="ORD02", date=today)

    rows = _table_body(client.get("/history?search=ORD02").data.decode())
    assert "ORD02" in rows and "ORD01" not in rows


def test_search_by_activity_number(client, insert_activity, today):
    insert_activity(activity_number=77, order_number="ORD77", date=today)
    insert_activity(activity_number=88, order_number="ORD88", date=today)

    rows = _table_body(client.get("/history?search=77").data.decode())
    assert "ORD77" in rows and "ORD88" not in rows


def test_search_applies_after_filters(client, insert_activity, today):
    """A record matching the search but excluded by a filter must not appear."""
    insert_activity(activity_number=1, order_number="ORD01", validation_result="PASS", date=today)
    insert_activity(activity_number=1, order_number="ORD99", validation_result="FAIL", date=today)

    rows = _table_body(client.get("/history?result=FAIL&search=ORD01").data.decode())
    assert "ORD01" not in rows


# --- Sorting ---

def test_sort_ascending_and_descending(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", date=today, hour=9)
    insert_activity(activity_number=2, order_number="ORD02", date=today, hour=10)
    insert_activity(activity_number=3, order_number="ORD03", date=today, hour=11)

    asc = _order_numbers_in_order(
        client.get("/history?sort=activity_number&order=asc").data.decode()
    )
    desc = _order_numbers_in_order(
        client.get("/history?sort=activity_number&order=desc").data.decode()
    )
    assert asc.index("ORD01") < asc.index("ORD03")
    assert desc.index("ORD03") < desc.index("ORD01")


def test_numeric_sort_handles_string_stored_weights(client, insert_activity, today):
    """
    Weights are stored as strings; sorting must be numeric, not lexicographic
    (otherwise "9" would sort after "100").
    """
    insert_activity(activity_number=1, order_number="ORD01", date=today, actual_weight="9")
    insert_activity(activity_number=2, order_number="ORD02", date=today, actual_weight="100")

    asc = _order_numbers_in_order(
        client.get("/history?sort=actual_weight&order=asc").data.decode()
    )
    assert asc.index("ORD01") < asc.index("ORD02")


def test_percent_sort_strips_percent_sign(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", date=today, weight_difference_percent="9.0%")
    insert_activity(activity_number=2, order_number="ORD02", date=today, weight_difference_percent="100.0%")

    asc = _order_numbers_in_order(
        client.get("/history?sort=weight_difference_percent&order=asc").data.decode()
    )
    assert asc.index("ORD01") < asc.index("ORD02")


# --- Pagination ---

@pytest.mark.parametrize("per_page", [25, 50, 100])
def test_allowed_per_page_values(client, per_page):
    resp = client.get(f"/history?per_page={per_page}")
    assert resp.status_code == 200
    assert f'value="{per_page}" selected' in resp.data.decode()


@pytest.mark.parametrize("bad", ["999", "0", "-5", "abc", "1000000"])
def test_invalid_per_page_falls_back_to_25(client, bad):
    resp = client.get(f"/history?per_page={bad}")
    assert resp.status_code == 200
    assert 'value="25" selected' in resp.data.decode()


def test_pagination_limits_rows_and_preserves_filters(client, insert_activity, today):
    for n in range(1, 31):
        insert_activity(activity_number=n, order_number=f"ORD{n:02d}", date=today)

    body = client.get("/history?per_page=25&result=PASS").data.decode()
    assert body.count("View Details") == 25
    assert "Page 1 of 2" in body
    # Next link must carry the active filter through
    assert "result=PASS" in body
    assert "page=2" in body


def test_second_page_shows_remaining_rows(client, insert_activity, today):
    for n in range(1, 31):
        insert_activity(activity_number=n, order_number=f"ORD{n:02d}", date=today)

    body = client.get("/history?per_page=25&page=2").data.decode()
    assert body.count("View Details") == 5


# --- Flags column ---

def test_flags_show_for_yes_and_no_but_not_untouched(client, insert_activity, today):
    """
    Regression: flags used to render only for "YES". An explicit "NO" is also
    a review decision and must show (visually distinct), while a genuinely
    untouched record shows the dash placeholder.
    """
    insert_activity(activity_number=1, order_number="ORD01", date=today, mark_discuss="YES")
    insert_activity(activity_number=2, order_number="ORD02", date=today, mark_ocr_wrong="NO")
    insert_activity(activity_number=3, order_number="ORD03", date=today)  # untouched

    body = client.get("/history").data.decode()
    assert "flag-badge--discuss" in body   # YES -> colored badge
    assert "flag-badge--no" in body        # NO   -> muted badge
    assert "flag-badge--none" in body      # untouched -> dash


def test_process_error_has_its_own_flag(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", date=today, mark_process_error="YES")
    body = client.get("/history").data.decode()
    assert "flag-badge--process" in body


def test_comment_flag_shown(client, insert_activity, today):
    insert_activity(activity_number=1, order_number="ORD01", date=today, review_comment="note")
    assert "flag-badge--comment" in client.get("/history").data.decode()


# --- Empty state ---

def test_empty_state_when_no_matches(client):
    body = client.get("/history").data.decode()
    assert "No matching activity records" in body
