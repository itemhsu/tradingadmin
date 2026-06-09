"""帳戶分頁深連結：momentum_url / dashboard_url 純函式測試。

驗證「點策略 → 只比 S&P500 + NASDAQ + 該帳戶策略」與「Dashboard 預設此帳戶」
組出來的網址正確，且重用既有 momentum 頁（?sel=）、不靠檔名巧合。
"""
from admin_gui.views.accounts_view import momentum_url, dashboard_url

OWNER = "itemhsu"
BASE = f"https://{OWNER}.github.io/tech-rebalance-dashboard/"


def test_momentum_url_includes_two_benchmarks_plus_strategy():
    assert momentum_url(OWNER, "d2p2t6") == \
        BASE + "momentum/?sel=bench_sp500,bench_nasdaq100,d2p2t6"


def test_momentum_url_for_each_known_account_strategy():
    for strat in ("top10", "d2p2t6", "mom_6m_t20", "weekly_top10"):
        url = momentum_url(OWNER, strat)
        assert url.startswith(BASE + "momentum/?sel=")
        # 永遠帶兩基準 + 該策略，且策略在最後
        assert url.endswith(f"bench_sp500,bench_nasdaq100,{strat}")


def test_momentum_url_empty_strategy_falls_back_to_benchmarks_only():
    # 無策略 → 只帶兩基準（天然 fallback，不報錯）
    assert momentum_url(OWNER, "") == \
        BASE + "momentum/?sel=bench_sp500,bench_nasdaq100"


def test_momentum_url_unknown_strategy_still_emitted_verbatim():
    # 不驗證：未知策略照樣帶上，交給回測頁自動忽略
    url = momentum_url(OWNER, "no_such_strat")
    assert url.endswith(",no_such_strat")


def test_dashboard_url_sets_account_default():
    assert dashboard_url(OWNER, "2") == BASE + "mvp_dashboard.html?a=2"


def test_urls_use_owner_dynamically():
    assert momentum_url("alice", "top10").startswith(
        "https://alice.github.io/tech-rebalance-dashboard/")
    assert dashboard_url("bob", "1").startswith(
        "https://bob.github.io/tech-rebalance-dashboard/")
