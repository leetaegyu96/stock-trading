"""대시보드 데모/화면점검용 시드 데이터 (simcore DB).

⚠️ 경고: DATABASE_URL 이 가리키는 DB의 거래·자산·포지션 데이터를 전부 지우고
데모 데이터로 교체한다. 라이브 데몬이 쌓은 실데이터가 있으면 사라진다.
실행하려면 --force 플래그가 필요하다:

    python dashboard/scripts/seed_demo.py --force
"""
import sys

if "--force" not in sys.argv:
    sys.exit("이 스크립트는 DB를 초기화합니다. 의도가 맞으면 --force 를 붙여 실행하세요.")

import math
import os
import random
from datetime import date, datetime, timedelta

from simcore.live import db

URL = os.environ["DATABASE_URL"]
engine = db.make_engine(URL)
db.create_all(engine)
Session = db.make_session_factory(engine)

random.seed(42)

CHARS = {
    "국내형": {"cur": "KRW", "drift": 0.0009, "vol": 0.011},
    "해외형": {"cur": "USD", "drift": 0.0005, "vol": 0.013},
    "범용형": {"cur": "KRW", "drift": 0.0007, "vol": 0.009},
}
START = date(2026, 1, 5)
DAYS = 130
INIT = 100_000_000.0

with Session() as s:
    # 초기화
    for t in (db.EquityPoint, db.TradeRow, db.CapitalFlowRow, db.FlowRequest,
              db.PositionRow, db.CashBalance, db.Cooldown, db.PendingOrder,
              db.DailyBarRow, db.UniverseRow, db.CharacterRow):
        s.query(t).delete()
    s.commit()

    d0 = START
    for name, cfg in CHARS.items():
        s.add(db.CharacterRow(name=name, base_currency=cfg["cur"]))
        # 초기 입금
        s.add(db.CapitalFlowRow(date=d0, character=name, amount_krw=INIT, fx_rate=1300.0))
        # 자산곡선 (거래일만)
        eq = INIT
        cur = d0
        n = 0
        while n < DAYS:
            if cur.weekday() < 5:
                r = random.gauss(cfg["drift"], cfg["vol"])
                eq = max(eq * (1 + r), INIT * 0.7)
                s.add(db.EquityPoint(ts=datetime(cur.year, cur.month, cur.day, 15, 40),
                                     character=name, equity_krw=round(eq, 0)))
                n += 1
            cur += timedelta(days=1)
    # 국내형 중간 입금(TWR 검증용)
    s.add(db.CapitalFlowRow(date=START + timedelta(days=60), character="국내형",
                            amount_krw=5_000_000.0, fx_rate=1300.0))
    s.commit()

    # 보유 종목 + 현금
    POS = {
        "국내형": [
            ("005930", "KR", 180, 265300.0, 68),
            ("000660", "KR", 22, 1915000.0, 41),
            ("086790", "KR", 310, 118400.0, 12),
            ("035420", "KR", 47, 207800.0, 5),
        ],
        "해외형": [
            ("AAPL", "US", 61, 292.4, 55),
            ("MSFT", "US", 38, 371.2, 30),
            ("NVDA", "US", 74, 212.6, 9),
        ],
        "범용형": [
            ("005930", "KR", 120, 271400.0, 33),
            ("373220", "KR", 18, 297500.0, 21),
            ("AMZN", "US", 44, 232.1, 14),
        ],
    }
    LAST = {"005930": 79300.0, "000660": 2076000.0, "086790": 122300.0,
            "035420": 251500.0, "373220": 315500.0,
            "AAPL": 310.66, "MSFT": 388.84, "NVDA": 196.93, "AMZN": 245.98}
    CASH = {"국내형": ("KRW", 8_240_000.0), "해외형": ("USD", 6120.0), "범용형": ("KRW", 12_400_000.0)}

    last_day = START + timedelta(days=200)
    seeded_bars: set[str] = set()
    for name, rows in POS.items():
        cur_code, amt = CASH[name]
        s.add(db.CashBalance(character=name, currency=cur_code, amount=amt))
        if cur_code != "KRW":
            s.add(db.CashBalance(character=name, currency="KRW", amount=0.0))
        else:
            s.add(db.CashBalance(character=name, currency="USD", amount=0.0))
        for sym, mkt, qty, avg, held in rows:
            s.add(db.PositionRow(character=name, symbol=sym, market=mkt, quantity=qty,
                                 avg_price=avg, opened_date=last_day - timedelta(days=held)))
            # daily_bars 최근 5거래일 (KIS 폴백용) — 심볼당 1회만
            if sym in seeded_bars:
                continue
            seeded_bars.add(sym)
            px = LAST[sym]
            for k in range(5):
                dd = last_day - timedelta(days=k)
                if dd.weekday() >= 5:
                    continue
                wig = 1 + math.sin(k) * 0.01
                s.add(db.DailyBarRow(market=mkt, symbol=sym, date=dd,
                                     open=px * wig * 0.995, high=px * wig * 1.01,
                                     low=px * wig * 0.985, close=px * (1 - 0.004 * k),
                                     volume=1_000_000 + k * 50_000))
    s.commit()

    # 거래내역
    G = ["G1", "G2", "G4", "G5", "G7"]
    R = ["R1", "R2", "R4"]
    TR = {
        "국내형": [
            ("005930", "KR", "BUY", 180, 265300.0, "SIGNAL_BUY", G + ["G3"], [], 0.0, 95),
            ("068270", "KR", "BUY", 113, 175573.0, "SIGNAL_BUY", G, [], 0.0, 82),
            ("068270", "KR", "SELL", 113, 163283.0, "STOP_LOSS", [], [], -1419227.0, 70),
            ("373220", "KR", "BUY", 54, 367500.0, "SIGNAL_BUY", G + ["G6"], [], 0.0, 66),
            ("373220", "KR", "SELL", 54, 422625.0, "TAKE_PROFIT", [], [], 2939094.0, 58),
            ("000660", "KR", "BUY", 22, 1915000.0, "SIGNAL_BUY", G, [], 0.0, 41),
            ("086790", "KR", "BUY", 310, 118400.0, "SIGNAL_BUY", G + ["G3", "G6"], [], 0.0, 12),
            ("035420", "KR", "BUY", 47, 207800.0, "SIGNAL_BUY", G, [], 0.0, 5),
        ],
        "해외형": [
            ("AAPL", "US", "BUY", 61, 292.4, "SIGNAL_BUY", G, [], 0.0, 55),
            ("TSLA", "US", "BUY", 33, 423.1, "SIGNAL_BUY", G, [], 0.0, 50),
            ("TSLA", "US", "SELL", 33, 434.9, "SIGNAL_SELL", [], R, 375.5, 38),
            ("MSFT", "US", "BUY", 38, 371.2, "SIGNAL_BUY", G + ["G6"], [], 0.0, 30),
            ("GOOGL", "US", "BUY", 44, 310.5, "SIGNAL_BUY", G, [], 0.0, 26),
            ("GOOGL", "US", "SELL", 44, 301.3, "SIGNAL_SELL", [], R, -416.5, 15),
            ("NVDA", "US", "BUY", 74, 212.6, "SIGNAL_BUY", G + ["G3"], [], 0.0, 9),
        ],
        "범용형": [
            ("005930", "KR", "BUY", 120, 271400.0, "SIGNAL_BUY", G, [], 0.0, 33),
            ("196170", "KR", "BUY", 41, 484000.0, "SIGNAL_BUY", G + ["G3", "G6"], [], 0.0, 60),
            ("196170", "KR", "SELL", 41, 556600.0, "TAKE_PROFIT", [], [], 2938946.0, 47),
            ("373220", "KR", "BUY", 18, 297500.0, "SIGNAL_BUY", G, [], 0.0, 21),
            ("AMZN", "US", "BUY", 44, 232.1, "SIGNAL_BUY", G, [], 0.0, 14),
            ("KO", "US", "BUY", 190, 71.69, "SIGNAL_BUY", G, [], 0.0, 90),
            ("KO", "US", "SELL", 190, 68.92, "SIGNAL_SELL", [], R, -538.6, 77),
        ],
    }
    for name, rows in TR.items():
        for sym, mkt, side, qty, px, reason, g, r, pnl, ago in rows:
            dd = last_day - timedelta(days=ago)
            fee = round(qty * px * 0.00015, 2)
            s.add(db.TradeRow(ts=datetime(dd.year, dd.month, dd.day, 9, 1),
                              date=dd, character=name, symbol=sym, market=mkt,
                              side=side, quantity=qty, price=px, fee=fee,
                              tax=round(qty * px * 0.0015, 2) if side == "SELL" and mkt == "KR" else 0.0,
                              reason=reason, green_count=len(g), red_count=len(r),
                              fired=g + r, realized_pnl=pnl))
    s.commit()
print("시드 완료: 3캐릭터 / equity", DAYS, "일 / 포지션·거래·입출금·일봉")
