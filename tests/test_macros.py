"""
Shared Jinja macros (app/templates/_macros.html).

These replaced the same colour-mapping ternary that was inlined six times
across three templates. The important thing to protect is that
badge_class() and pass_fail_class() are NOT interchangeable - see the test
at the bottom.
"""

import pytest

MACRO_IMPORT = '{% from "_macros.html" import badge_class, yes_no_class, pass_fail_class %}'


def render(app, expression):
    with app.app_context():
        from flask import render_template_string
        return render_template_string(MACRO_IMPORT + "{{ " + expression + " }}").strip()


@pytest.mark.parametrize(
    "result,expected",
    [
        ("PASS", "pass"),
        ("FAIL", "fail"),
        ("MISSING_DATA", "warn"),
        ("INVALID_WEIGHT_DATA", "warn"),
        ("SOMETHING_ELSE", "muted"),
        ("", "muted"),
        (None, "muted"),
    ],
)
def test_badge_class(app, result, expected):
    assert render(app, f"badge_class({result!r})") == expected


@pytest.mark.parametrize(
    "value,expected",
    [("YES", "pass"), ("NO", "fail"), ("--", "muted"), ("", "muted"), (None, "muted")],
)
def test_yes_no_class(app, value, expected):
    assert render(app, f"yes_no_class({value!r})") == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PASS", "pass"),
        ("FAIL", "fail"),
        ("MISSING", "muted"),
        ("INVALID", "muted"),
        ("", "muted"),
        (None, "muted"),
    ],
)
def test_pass_fail_class(app, value, expected):
    assert render(app, f"pass_fail_class({value!r})") == expected


def test_badge_class_and_pass_fail_class_are_not_interchangeable(app):
    """
    Deliberate difference, easy to "helpfully" collapse into one macro later
    and silently change the UI:

      badge_class    : MISSING_DATA -> warn  (orange - inconclusive result)
      pass_fail_class: MISSING      -> muted (grey  - used for weight_result)
    """
    assert render(app, "badge_class('MISSING_DATA')") == "warn"
    assert render(app, "pass_fail_class('MISSING')") == "muted"


def test_macros_match_the_javascript_mapping():
    """
    live_monitoring.js does the same mapping client-side for socket updates.
    If one side changes, colours would differ between a fresh page load and
    a live update - so keep the two in step.
    """
    js = open("app/static/js/live_monitoring.js").read()
    assert "if (result === 'PASS') return 'pass';" in js
    assert "if (result === 'FAIL') return 'fail';" in js
    assert "MISSING_DATA" in js and "'warn'" in js
