from dataclasses import replace
from simcore.config import Config

def test_defaults_match_trading_rules():
    c = Config()
    assert c.rules.buy_threshold == 7
    assert c.rules.sell_threshold == 3
    assert c.rules.stop_loss_pct == -0.07
    assert c.rules.take_profit_pct == 0.15
    assert c.rules.max_positions == 5
    assert c.rules.cooldown_days == 2
    assert c.costs.kr_commission == 0.00015
    assert c.costs.kr_tax == 0.0015
    assert c.costs.us_commission == 0.0009
    assert c.costs.fx_fee == 0.001
    assert c.costs.slippage == 0.0
    assert c.initial_capital_krw == 100_000_000

def test_override_with_replace():
    c = Config()
    c2 = replace(c, rules=replace(c.rules, buy_threshold=5))
    assert c2.rules.buy_threshold == 5
    assert c.rules.buy_threshold == 7  # 원본 불변
