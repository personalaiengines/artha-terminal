"""
ARTHA Terminal - list/screen questions

Found by running real questions through the analyst: "Show me pharma stocks"
routed to `market`, which grounds on a breadth snapshot plus a web search —
nothing that lists companies. It answered "*No individual Indian pharma stock
prices were in the provided feed*" and then recommended Johnson & Johnson,
AbbVie and Merck, while the local DB held the full Nifty Pharma membership.

These run against db/artha.db, the repo copy, which carries index membership
but almost no fundamentals — so they must assert the shape of the block, never
which particular columns a given sector happens to populate.
"""

import pytest

from agent.chat import (extract_symbols, route_intent, screen_display,
                        screen_facts, screen_group)


# --- routing ----------------------------------------------------------

def test_list_questions_route_to_screen():
    for q in ["Show me pharma stocks",
              "Best IT stocks to buy now",
              "Which banks are cheapest?",
              "top gainers among metal stocks",
              "list the FMCG companies"]:
        assert route_intent(q, extract_symbols(q)) == "screen", q


@pytest.mark.needs_data
def test_a_named_deep_dive_still_wins_over_screening():
    # "Do a deep dive on Infosys" must not become a sector list just because
    # the IT group is nameable from the word "Infosys"... it isn't, but guard
    # the precedence anyway: explicit intents outrank the screen heuristic.
    q = "Do a deep dive on Infosys"
    assert route_intent(q, extract_symbols(q)) == "deep"
    q2 = "Compare TCS vs Infosys"
    assert route_intent(q2, extract_symbols(q2)) == "compare"


def test_screen_needs_a_resolvable_group():
    # A list question about something with no stored index must not claim to
    # screen; it falls back to the general market path.
    q = "show me the best stocks"
    assert screen_group(q) is None
    assert route_intent(q, extract_symbols(q)) != "screen"


def test_group_aliases_map_to_the_right_index():
    cases = {
        "pharma stocks": "pharma", "drug makers": "pharma",
        "IT stocks": "it", "software companies": "it",
        "psu bank stocks": "psubank", "banking names": "banknifty",
        "real estate stocks": "realty", "oil and gas companies": "oilgas",
        "midcap names": "niftymidcap150",
    }
    for q, key in cases.items():
        got = screen_group(q)
        assert got and got[0] == key, f"{q!r} -> {got}"


def test_more_specific_group_wins():
    # "psu bank" must not be swallowed by "bank", nor "oil and gas" by "gas".
    assert screen_group("psu bank stocks")[0] == "psubank"
    assert screen_group("oil and gas stocks")[0] == "oilgas"


# --- grounding --------------------------------------------------------

@pytest.mark.needs_data
def test_screen_grounds_on_real_constituents():
    out = screen_facts("Show me pharma stocks")
    assert out, "screen produced no grounding block"
    assert "Pharma" in out
    # Indian names from the stored NSE membership, and an explicit fence
    # against the model adding its own.
    assert "do not add companies that are not in this table" in out
    for foreign in ("Johnson", "AbbVie", "Merck", "Pfizer"):
        assert foreign not in out


def test_unknown_group_produces_nothing_rather_than_a_guess():
    assert screen_facts("show me the best stocks") == ""


def _table(block: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in block.splitlines() if l.startswith("|")]
    head = [c.strip() for c in lines[0].strip("|").split("|")]
    body = [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]
    return head, body


@pytest.mark.needs_data
def test_every_printed_column_carries_at_least_one_value():
    # A column of nothing but "n/a" costs prompt space and says nothing. Which
    # columns qualify depends on what has been ingested, so assert the rule
    # rather than a specific column list.
    for q in ("Show me pharma stocks", "Which banks are the biggest?"):
        head, body = _table(screen_facts(q))
        for i, col in enumerate(head):
            if col in ("Symbol", "Company", "Close"):
                continue
            assert any(row[i] != "n/a" for row in body), f"{col!r} is empty in {q!r}"


@pytest.mark.needs_data
def test_absent_columns_are_declared_rather_than_silently_dropped():
    block = screen_facts("Show me pharma stocks")
    head, _ = _table(block)
    if "NOT AVAILABLE" in block:
        declared = block.split("NOT AVAILABLE for these names:")[1].split(".")[0]
        for col in ("P/E", "ROE%", "Score"):
            assert col in head or col in declared, f"{col} vanished without a word"


@pytest.mark.needs_data
def test_display_table_is_the_heading_and_rows_only():
    # The figures the user reads come from the DB, not re-typed by the model.
    block = screen_facts("Show me pharma stocks")
    shown = screen_display(block)

    assert shown.startswith("### ")
    assert "| DIVISLAB |" in shown
    assert shown.count("\n") >= 15          # heading + header + rule + 15 rows
    # The prompt-only scaffolding must not leak onto the user's screen.
    assert "NOT AVAILABLE" not in shown
    assert "do not add companies" not in shown
    assert "NOTE:" not in shown


def test_display_table_survives_a_block_with_no_footer():
    assert screen_display("### X\n| A |\n|---|\n| 1 |") == "### X\n| A |\n|---|\n| 1 |"
    assert screen_display("") == ""


@pytest.mark.needs_data
def test_a_ranking_nobody_can_compute_is_disclosed():
    # Ranking by an all-null column silently degrades to default order while
    # the heading still says "ranked by lowest P/E". Whether P/E is populated
    # depends on the DB in front of us, so assert the implication, not the
    # branch: no P/E column present <=> the disclaimer must be there.
    out = screen_facts("Which banks are cheapest?")
    head, _ = _table(out)
    assert ("P/E" in head) != ("NOT ranked by it" in out)
