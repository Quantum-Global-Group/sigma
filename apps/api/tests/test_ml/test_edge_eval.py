"""Tests for ml/edge_eval.py (the centralized alpha gate) and ml/news.py."""

import sys
from pathlib import Path

_api = Path(__file__).parents[2]
sys.path.insert(0, str(_api))

import numpy as np
import pytest

from ml import edge_eval
from ml.news import NewsEvent, fetch_news, parse_news


# ---------------------------------------------------------------------------
# trade_stats
# ---------------------------------------------------------------------------

def test_trade_stats_empty():
    s = edge_eval.trade_stats([], cost_frac=0.0008)
    assert s.n == 0 and s.net_bps == 0.0


def test_trade_stats_net_subtracts_cost_once():
    # five +50bps trades, cost 8bps round-trip → net 42bps each
    s = edge_eval.trade_stats([0.005] * 5, cost_frac=0.0008)
    assert s.n == 5
    assert s.gross_bps == pytest.approx(50.0)
    assert s.net_bps == pytest.approx(42.0)
    assert s.win_rate == 1.0
    assert s.total_pct == pytest.approx(5 * 0.0042 * 100)


def test_trade_stats_win_rate_and_sharpe_sign():
    s = edge_eval.trade_stats([0.01, -0.01, 0.02, -0.005], cost_frac=0.0)
    assert s.win_rate == pytest.approx(0.5)
    # mean > 0 here → positive per-trade sharpe
    assert s.sharpe > 0


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

def test_gate_passes_on_positive_edge():
    s = edge_eval.trade_stats([0.005] * 150, cost_frac=0.0008)
    ok, reasons = edge_eval.gate(s)
    assert ok and reasons == []


def test_gate_fails_on_too_few_trades():
    s = edge_eval.trade_stats([0.005] * 20, cost_frac=0.0008)
    ok, reasons = edge_eval.gate(s)
    assert not ok and any("trades" in r for r in reasons)


def test_gate_fails_when_cost_eats_edge():
    # +5bps gross, 8bps cost → net negative
    s = edge_eval.trade_stats([0.0005] * 200, cost_frac=0.0008)
    ok, reasons = edge_eval.gate(s)
    assert not ok and any("not positive" in r for r in reasons)


def test_gate_fails_on_nonpositive_sharpe():
    s = edge_eval.trade_stats([-0.01] * 200, cost_frac=0.0)
    ok, reasons = edge_eval.gate(s)
    assert not ok


# ---------------------------------------------------------------------------
# chrono_split
# ---------------------------------------------------------------------------

def test_chrono_split_is_temporal_not_positional():
    # deliberately unsorted timestamps; train must be the EARLIEST 60%
    ts = np.array([5, 1, 4, 2, 3, 0, 9, 7, 8, 6])
    train, test = edge_eval.chrono_split(ts, train_frac=0.6)
    assert train.sum() == 6 and test.sum() == 4
    # every train timestamp precedes every test timestamp
    assert ts[train].max() < ts[test].min()


def test_chrono_split_empty():
    tr, te = edge_eval.chrono_split([], 0.6)
    assert tr.size == 0 and te.size == 0


def test_verdict_strings():
    good = edge_eval.trade_stats([0.005] * 150, cost_frac=0.0008)
    assert "PASS" in edge_eval.verdict("t1", good)
    bad = edge_eval.trade_stats([0.005] * 5, cost_frac=0.0008)
    assert "REJECT" in edge_eval.verdict("t1", bad)


# ---------------------------------------------------------------------------
# ml/news.py — parse + paginate + cache (no network)
# ---------------------------------------------------------------------------

def test_parse_news_maps_fields():
    payload = {"news": [
        {"created_at": "2025-01-02T14:00:00Z", "headline": "Beat", "summary": "s1", "source": "benzinga"},
        {"created_at": "2025-01-02T15:00:00Z", "headline": "Up", "summary": "", "source": "benzinga"},
        {"headline": "no timestamp dropped"},  # missing created_at → skipped
    ]}
    evs = parse_news(payload, "AAPL")
    assert len(evs) == 2
    assert evs[0].symbol == "AAPL" and evs[0].headline == "Beat"
    assert evs[0].text == "Beat. s1"


def test_fetch_news_paginates_with_injected_getter():
    pages = [
        {"news": [{"created_at": "2025-01-01T00:00:00Z", "headline": "a", "summary": ""}],
         "next_page_token": "tok"},
        {"news": [{"created_at": "2025-01-02T00:00:00Z", "headline": "b", "summary": ""}]},
    ]
    calls = []

    def fake_get(url, params):
        calls.append(params.get("page_token"))
        return pages[len(calls) - 1]

    evs = fetch_news("AAPL", "2025-01-01T00:00:00Z", getter=fake_get)
    assert [e.headline for e in evs] == ["a", "b"]
    assert calls == [None, "tok"]   # first page no token, second uses returned token


def test_fetch_news_survives_getter_error():
    def boom(url, params):
        raise RuntimeError("503")
    assert fetch_news("AAPL", "2025-01-01T00:00:00Z", getter=boom) == []


def test_news_event_text():
    e = NewsEvent("X", "2025-01-01T00:00:00Z", "Head", "Body")
    assert e.text == "Head. Body"
