"""Symbol extraction + intent routing.

Guards the bug this replaced: substring matching over 5173 symbols made
"Summarise this week's news" resolve to MARIS and "is the market overvalued"
to VALUE, each triggering a full deep dive on an unrelated microcap.
"""

import pytest

from agent.chat import extract_symbols, route_intent, trim_history, build_system


def test_no_false_positives_inside_words():
    for q in [
        "Summarise this week's market-moving news",
        "Is the market overvalued right now?",
        "What are the risks?",
        "How is breadth looking today?",
    ]:
        assert extract_symbols(q) == [], f"{q!r} matched {extract_symbols(q)}"


@pytest.mark.needs_data
def test_real_symbols_resolve():
    assert "TCS" in extract_symbols("What is TCS trading at?")
    assert extract_symbols("tcs pe ratio") == ["TCS"]
    # Punctuation and possessives must not block the boundary match.
    assert "TCS" in extract_symbols("What's TCS's P/E?")


@pytest.mark.needs_data
def test_multiple_symbols_in_order():
    got = extract_symbols("Compare TCS vs INFY fundamentals")
    assert got[:2] == ["TCS", "INFY"], got


def test_intent_routing():
    assert route_intent("Analyse the risk in my portfolio", []) == "portfolio"
    assert route_intent("Compare TCS vs INFY", ["TCS", "INFY"]) == "compare"
    assert route_intent("What's TCS's P/E?", ["TCS"]) == "lookup"
    assert route_intent("Do a deep dive on TCS", ["TCS"]) == "deep"
    assert route_intent("What's driving Bank Nifty today?", []) == "market"
    # Naming a stock is not on its own a request for a full workup.
    assert route_intent("Is TCS above its 200 DMA?", ["TCS"]) == "lookup"


def test_history_trimmed_and_normalised():
    hist = [{"role": "ai", "text": "hi"}, {"role": "user", "content": "yo"}] * 20
    out = trim_history(hist)
    assert len(out) <= 12
    assert {m["role"] for m in out} <= {"user", "assistant"}
    assert all(m["content"] for m in out)


def test_system_prompt_carries_data_and_intent():
    s = build_system("compare", ["### TCS\nP/E 30"])
    assert "P/E 30" in s and "side by side" in s
    assert "never advice" in s.lower() or "observations" in s.lower()


@pytest.mark.needs_data
def test_resolve_uses_history_for_pronoun_followups():
    from agent.chat import resolve
    hist = [{"role": "user", "content": "What is TCS P/E?"},
            {"role": "assistant", "content": "TCS P/E is 17.41."}]
    syms, intent = resolve("What about its debt?", hist)
    assert syms == ["TCS"], syms
    # Without history this used to route "market" and fire a web search.
    assert intent == "lookup", intent
    assert resolve("What about its debt?", [])[1] == "market"


@pytest.mark.needs_data
def test_instruction_words_are_not_subjects():
    """DEEP, RESEARCH, VALUE etc. are real tickers as well as instruction words.

    "Do a deep dive on TCS" resolved DEEP (a Basic Materials microcap) ahead of
    TCS and analysed the wrong company end to end.
    """
    from agent.chat import resolve
    for q, want in [
        ("Do a deep dive on TCS", "TCS"),
        ("Deep dive INFY", "INFY"),
        ("full analysis of WIPRO", "WIPRO"),
        ("research ITC for me", "ITC"),
        ("swot on SBIN", "SBIN"),
        ("What are the red flags on RELIANCE?", "RELIANCE"),
    ]:
        syms, intent = resolve(q, [])
        assert syms == [want], f"{q!r} -> {syms}"
        assert intent == "deep", f"{q!r} -> {intent}"


def test_regression_case_1_symbolless_question(monkeypatch):
    """A question naming no symbol must not bind a ticker the user never named.

    Live regression: "What is teh last closing price" answered about ACTIVE
    (Active Clothing Co, a microcap) because a prior turn contained the ordinary
    word "active". The price quoted was correct; the subject was invented.

    Hermetic on purpose — the dev DB has ~2411 symbols and no ACTIVE row while
    production has 5173, so this bug class is untestable against the real index.
    """
    import agent.chat as chat

    monkeypatch.setattr(chat, "_INDEX", [("ACTIVE", "ACTIVE"), ("TCS", "TCS")])

    assert chat.extract_symbols("How active is the market today?") == []

    hist = [{"role": "user", "content": "How active is the market today?"},
            {"role": "assistant", "content": "Overall activity was moderate..."}]
    assert chat.resolve("What is teh last closing price", hist) == ([], "market")

    # Session context still supplies the subject when the user actually named it.
    named = [{"role": "user", "content": "What is TCS P/E?"},
             {"role": "assistant", "content": "TCS P/E is 17.41."}]
    assert chat.resolve("What is teh last closing price", named) == (["TCS"], "lookup")


def test_company_names_resolve_to_symbols():
    """A question naming the company, not the ticker, still resolves.

    Asserted against whatever company_name the local DB actually holds — the
    dev DB and the deployed volume carry different vintages of the name data
    ("CENTRAL DEPO SER (I) LTD" vs "Central Depository Services (India) Limited"),
    so pinning a literal name here tests the fixture, not the matcher.
    """
    from db import get_connection
    with get_connection() as conn:
        row = conn.execute("""
            SELECT symbol, company_name FROM symbol_master
            WHERE company_name IS NOT NULL AND length(company_name) > 14
              AND company_name LIKE '% %' AND symbol NOT LIKE '%-%'
            ORDER BY symbol LIMIT 1
        """).fetchone()
    if not row:
        return  # empty universe (fresh checkout, no ETL run) — nothing to assert
    assert row["symbol"] in extract_symbols(f"tell me about {row['company_name']}"), row["symbol"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
