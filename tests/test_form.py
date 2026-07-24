"""Tests for how the search form fields are handled."""

from shopping_agent import db, web


def test_multiline_query_keeps_the_line_breaks_normalised():
    text = "caravana 4 plazas\r\nmenos de 15.000€\r\ncon calefacción\r\n"
    clean = web._query_from_form(text)
    assert clean == "caravana 4 plazas\nmenos de 15.000€\ncon calefacción"
    assert "\r" not in clean


def test_a_query_with_only_whitespace_ends_up_empty():
    assert web._query_from_form("  \r\n \n ") == ""


def test_km_are_free_with_no_steps_and_no_cap():
    # The browser used to require multiples of 10 starting at 1 (1, 11, ... 201): not anymore.
    assert web._radius_from_form("200") == 200
    assert web._radius_from_form("250,5") == 250.5
    assert web._radius_from_form("5000") == 5000


def test_the_multiline_query_is_stored_and_read_back_unchanged():
    text = "caravana 4 plazas\nmenos de 15.000€\ncon calefacción"
    bid = db.create_search(text, "Madrid", "ES", 6)
    assert db.get_search(bid)["consulta"] == text
