import pytest
from fastapi.testclient import TestClient

from simcore.live import db

from tests.dashboard.conftest import needs_db
from dashboard.backend.app import app, get_sf


def _client(sf):
    app.dependency_overrides[get_sf] = lambda: sf
    return TestClient(app)


def _release(sf):
    app.dependency_overrides.pop(get_sf, None)


@needs_db
def test_deposit_enqueues_positive_pending_flow_request(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="국내형", base_currency="KRW"))
        s.commit()

    client = _client(sf)
    try:
        r = client.post("/api/characters/국내형/deposit", json={"amount_krw": 1_000_000.0})
    finally:
        _release(sf)

    assert r.status_code == 200
    body = r.json()
    assert body["queued"] is True
    assert isinstance(body["request_id"], int)

    with sf() as s:
        rows = s.query(db.FlowRequest).filter_by(character="국내형").all()
    assert len(rows) == 1
    assert rows[0].amount_krw == 1_000_000.0
    assert rows[0].status == "pending"
    assert rows[0].liquidate == []


@needs_db
def test_withdraw_enqueues_negative_pending_flow_request_with_liquidate(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="해외형", base_currency="USD"))
        s.commit()

    client = _client(sf)
    try:
        r = client.post(
            "/api/characters/해외형/withdraw",
            json={"amount_krw": 500_000.0, "liquidate": ["AAPL"]},
        )
    finally:
        _release(sf)

    assert r.status_code == 200
    body = r.json()
    assert body["queued"] is True
    assert isinstance(body["request_id"], int)

    with sf() as s:
        rows = s.query(db.FlowRequest).filter_by(character="해외형").all()
    assert len(rows) == 1
    assert rows[0].amount_krw == -500_000.0
    assert rows[0].status == "pending"
    assert rows[0].liquidate == ["AAPL"]


@needs_db
def test_withdraw_without_liquidate_defaults_to_empty_list(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="범용형", base_currency="KRW"))
        s.commit()

    client = _client(sf)
    try:
        r = client.post("/api/characters/범용형/withdraw", json={"amount_krw": 10_000.0})
    finally:
        _release(sf)

    assert r.status_code == 200
    with sf() as s:
        [row] = s.query(db.FlowRequest).filter_by(character="범용형").all()
    assert row.amount_krw == -10_000.0
    assert row.liquidate == []


@needs_db
@pytest.mark.parametrize("amount", [0, -100.0])
def test_deposit_rejects_non_positive_amount(sf, amount):
    client = _client(sf)
    try:
        r = client.post("/api/characters/국내형/deposit", json={"amount_krw": amount})
    finally:
        _release(sf)

    assert r.status_code == 400
    with sf() as s:
        assert s.query(db.FlowRequest).count() == 0


@needs_db
@pytest.mark.parametrize("amount", [0, -100.0])
def test_withdraw_rejects_non_positive_amount(sf, amount):
    client = _client(sf)
    try:
        r = client.post("/api/characters/국내형/withdraw", json={"amount_krw": amount})
    finally:
        _release(sf)

    assert r.status_code == 400
    with sf() as s:
        assert s.query(db.FlowRequest).count() == 0


@needs_db
def test_deposit_rejects_unknown_character(sf):
    client = _client(sf)
    try:
        r = client.post("/api/characters/없는형/deposit", json={"amount_krw": 1_000.0})
    finally:
        _release(sf)

    assert r.status_code in (400, 404)
    with sf() as s:
        assert s.query(db.FlowRequest).count() == 0


@needs_db
def test_withdraw_rejects_unknown_character(sf):
    client = _client(sf)
    try:
        r = client.post("/api/characters/없는형/withdraw", json={"amount_krw": 1_000.0})
    finally:
        _release(sf)

    assert r.status_code in (400, 404)
    with sf() as s:
        assert s.query(db.FlowRequest).count() == 0
