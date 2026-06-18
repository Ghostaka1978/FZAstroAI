from pathlib import Path

from fzastro_ai.market_sources import (
    market_pulse_plain_text,
    perform_stock_compare,
    parse_market_pulse_payload,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_global_market_pulse_contract_is_wired_without_llm():
    market_sources = (PROJECT_ROOT / "fzastro_ai" / "market_sources.py").read_text(
        encoding="utf-8"
    )
    worker_text = (
        PROJECT_ROOT / "fzastro_ai" / "workers" / "web_search_worker.py"
    ).read_text(encoding="utf-8")
    actions_text = (
        PROJECT_ROOT / "fzastro_ai" / "actions" / "market_actions.py"
    ).read_text(encoding="utf-8")

    assert "GLOBAL_MARKET_PULSE_GROUPS" in market_sources
    for symbol in (
        "^GSPC",
        "^IXIC",
        "^FTSE",
        "^GDAXI",
        "^N225",
        "^VIX",
        "^TNX",
        "DX-Y.NYB",
        "CL=F",
        "GC=F",
        "CRM",
        "DBX",
    ):
        assert symbol in market_sources

    assert "def perform_global_market_pulse" in market_sources
    assert "[MARKET_PULSE]" in market_sources
    assert "def parse_market_pulse_payload" in market_sources
    assert "def market_pulse_plain_text" in market_sources
    assert "_format_market_pulse_markdown(payload)" in market_sources
    assert 'elif self.mode == "market_pulse":' in worker_text
    assert "perform_global_market_pulse()" in worker_text
    assert 'elif self.mode == "stock_compare":' in worker_text
    assert "perform_stock_compare(self.query)" in worker_text
    assert "def retrieve_global_market_pulse" in actions_text
    assert "def finish_global_market_pulse" in actions_text
    assert 'WebSearchWorker("global_market_pulse", mode="market_pulse")' in actions_text


def test_market_pulse_payload_parses_and_copies_as_plain_text():
    payload = parse_market_pulse_payload(
        '[MARKET_PULSE]\n{"title":"Global Market Pulse","retrieved_at":"now",'
        '"source_name":"source","groups":[{"name":"US","rows":[{"label":"S&P 500",'
        '"ticker":"^GSPC","last":"7,500.64","change_text":"+80.54 / +1.09%",'
        '"status":"After hours","direction":"up"}]}]}'
    )

    assert payload is not None
    plain = market_pulse_plain_text(payload)
    assert "Global Market Pulse" in plain
    assert "S&P 500 (^GSPC): 7,500.64; +80.54 / +1.09%; After hours" in plain


def test_stock_compare_formats_current_quote_table(monkeypatch):
    def fake_quote(ticker):
        prices = {"CRM": 250.25, "DBX": 31.5}
        changes = {"CRM": 3.25, "DBX": -0.5}
        pct = {"CRM": 1.31, "DBX": -1.56}
        names = {"CRM": "Salesforce", "DBX": "Dropbox"}
        return (
            '[STOCK_QUOTE]\n{"ticker":"'
            + ticker
            + '","company_name":"'
            + names[ticker]
            + '","price":'
            + str(prices[ticker])
            + ',"currency":"USD","change":'
            + str(changes[ticker])
            + ',"percentage_change":'
            + str(pct[ticker])
            + ',"market_status":"After hours","quote_timestamp":"now",'
            + '"exchange":"NYSE","source_name":"Yahoo Finance",'
            + '"source_url":"https://finance.yahoo.com/quote/'
            + ticker
            + '","retrieved_at":"now"}'
        )

    monkeypatch.setattr("fzastro_ai.market_sources.perform_stock_quote", fake_quote)

    text = perform_stock_compare("Compare CRM and DBX stocks")

    assert text.startswith("[MARKET_COMPARE]")
    assert "| Salesforce | CRM | $250.25 | +3.25 USD / +1.31% |" in text
    assert "| Dropbox | DBX | $31.50 | -0.50 USD / -1.56% |" in text
    assert "[Yahoo Finance](https://finance.yahoo.com/quote/CRM)" in text
