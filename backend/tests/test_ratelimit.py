"""Admission control: per-IP limits, global daily cap, concurrency cap, proxy-aware client IP.

Time is a fake clock (also patched into the `limits` library's memory storage); nothing sleeps.
"""

import logging
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from limits.storage import memory
from sqlmodel import Session

from app.core.ratelimit import client_ip, seconds_until_utc_midnight
from app.db.models import Debate
from tests.conftest import demo_factory, wait_until

Q = "What is 17 * 24?"


class FakeClock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    c = FakeClock()
    monkeypatch.setattr(memory, "time", SimpleNamespace(time=c))  # the limiter's storage clock
    return c


@pytest.fixture
def limited(make_client, clock):
    """`async with limited(**settings) as (client, app)`: limits on, clock under test control."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _make(provider_factory=None, **settings):
        settings.setdefault("rate_limit_enabled", True)
        async with make_client(provider_factory, **settings) as (client, app):
            app.state.admission._clock = clock
            yield client, app

    return _make


async def post(client, question=Q, **headers):
    return await client.post("/api/debates", json={"question": question}, headers=headers)


async def post_and_finish(client, app, question=Q, **headers):
    resp = await post(client, question, **headers)
    if resp.status_code == 201:
        debate_id = resp.json()["id"]
        await wait_until(lambda: debate_id not in app.state.service._channels)
    return resp


def add_debate(app, *, status="completed", api_calls=5, created_at=None, fallbacks=0):
    """A stored debate row, for tests of the global cap."""
    with Session(app.state.service.engine) as s:
        s.add(
            Debate(
                id=f"seed-{time.monotonic_ns()}",
                question="seed",
                mode="answer",
                status=status,
                created_at=created_at or datetime.now(UTC),
                stats_json={"api_calls": api_calls, "fallbacks": fallbacks, "calls": 7},
            )
        )
        s.commit()


# --- client IP -----------------------------------------------------------------------------


def test_forwarded_for_is_ignored_without_a_trusted_proxy():
    assert client_ip("10.0.0.1", "6.6.6.6", 0) == "10.0.0.1"


def test_trusted_proxy_takes_the_nth_entry_from_the_right():
    assert client_ip("10.0.0.1", "1.1.1.1", 1) == "1.1.1.1"
    assert client_ip("10.0.0.1", "9.9.9.9, 1.1.1.1", 1) == "1.1.1.1"
    assert client_ip("10.0.0.1", "9.9.9.9, 1.1.1.1, 172.16.0.5", 2) == "1.1.1.1"


def test_entries_a_client_prepends_are_never_read():
    honest = client_ip("10.0.0.1", "1.1.1.1", 1)
    spoofed = client_ip("10.0.0.1", "8.8.8.8, 7.7.7.7, 1.1.1.1", 1)
    assert honest == spoofed == "1.1.1.1"


@pytest.mark.parametrize("header", [None, "", "not-an-ip", "1.1.1.1", "999.1.1.1"])
def test_missing_short_or_malformed_header_falls_back_to_the_peer(header):
    hops = 2 if header == "1.1.1.1" else 1
    assert client_ip("10.0.0.1", header, hops) == "10.0.0.1"


def test_ipv6_is_normalised():
    assert client_ip("10.0.0.1", "2001:DB8:0:0:0:0:0:1", 1) == "2001:db8::1"


def test_seconds_until_midnight():
    noon = datetime(2026, 10, 19, 12, 0, tzinfo=UTC).timestamp()
    assert seconds_until_utc_midnight(noon) == 12 * 3600


# --- defaults ------------------------------------------------------------------------------


async def test_limits_are_off_by_default(make_client):
    async with make_client() as (client, app):
        for i in range(8):
            assert (await post(client, f"q{i}")).status_code == 201
        await wait_until(lambda: not app.state.service._channels)


async def test_startup_logs_whether_rate_limiting_is_on(make_client, caplog):
    caplog.set_level(logging.INFO, logger="app.admission")
    async with make_client():
        pass
    assert any("rate limiting OFF" in r.getMessage() for r in caplog.records)
    caplog.clear()
    async with make_client(rate_limit_enabled=True, rate_limit_per_hour=7, global_daily_cap=9):
        pass
    line = next(r.getMessage() for r in caplog.records if r.name == "app.admission")
    assert "rate limiting ON" in line and "7/hour" in line and "cap 9" in line


# --- per-IP --------------------------------------------------------------------------------


async def test_hourly_limit_returns_429_with_retry_after_and_a_friendly_body(limited, clock):
    async with limited(rate_limit_per_hour=2) as (client, app):
        assert (await post_and_finish(client, app, "a")).status_code == 201
        clock.advance(10)
        assert (await post_and_finish(client, app, "b")).status_code == 201
        clock.advance(10)
        resp = await post(client, "c")
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"] == "rate_limited" and body["scope"] == "ip_hour"
    assert "this hour" in body["message"]
    # The oldest request leaves the window 3600s after it was made, 20s ago.
    assert body["retry_after_s"] == 3580
    assert resp.headers["Retry-After"] == "3580"


async def test_window_moves_with_time_and_the_ip_can_start_again(limited, clock):
    async with limited(rate_limit_per_hour=1, rate_limit_per_day=100) as (client, app):
        assert (await post_and_finish(client, app, "a")).status_code == 201
        assert (await post(client, "b")).status_code == 429
        clock.advance(3599)
        assert (await post(client, "b")).status_code == 429
        clock.advance(2)
        assert (await post_and_finish(client, app, "b")).status_code == 201


async def test_daily_limit(limited, clock):
    async with limited(rate_limit_per_hour=100, rate_limit_per_day=2) as (client, app):
        await post_and_finish(client, app, "a")
        await post_and_finish(client, app, "b")
        resp = await post(client, "c")
        assert resp.status_code == 429 and resp.json()["scope"] == "ip_day"
        clock.advance(86401)
        assert (await post_and_finish(client, app, "c")).status_code == 201


async def test_invalid_requests_are_not_counted(limited):
    async with limited(rate_limit_per_hour=1) as (client, app):
        assert (await client.post("/api/debates", json={"question": "   "})).status_code == 422
        assert (await post_and_finish(client, app, "a")).status_code == 201


async def test_reads_are_never_limited(limited):
    async with limited(rate_limit_per_hour=1, rate_limit_per_day=1) as (client, app):
        resp = await post_and_finish(client, app, "a")
        debate_id = resp.json()["id"]
        assert (await post(client, "b")).status_code == 429
        for _ in range(10):
            assert (await client.get(f"/api/debates/{debate_id}")).status_code == 200
            assert (await client.get(f"/api/debates/{debate_id}/stream")).status_code == 200
            assert (await client.get("/api/debates")).status_code == 200
            assert (await client.get(f"/api/debates/{debate_id}/reveal")).status_code == 200


async def test_different_ips_have_separate_allowances(limited):
    async with limited(rate_limit_per_hour=1, trusted_proxy=1) as (client, app):
        assert (
            await post_and_finish(client, app, "a", **{"X-Forwarded-For": "1.1.1.1"})
        ).status_code == 201
        assert (await post(client, "b", **{"X-Forwarded-For": "2.2.2.2"})).status_code == 201
        assert (await post(client, "c", **{"X-Forwarded-For": "1.1.1.1"})).status_code == 429


async def test_a_spoofed_header_does_not_help_without_a_trusted_proxy(limited):
    async with limited(rate_limit_per_hour=1) as (client, app):
        await post_and_finish(client, app, "a", **{"X-Forwarded-For": "1.1.1.1"})
        resp = await post(client, "b", **{"X-Forwarded-For": "2.2.2.2"})
    assert resp.status_code == 429  # everyone is the socket peer


async def test_a_spoofed_left_entry_does_not_help_behind_a_trusted_proxy(limited):
    async with limited(rate_limit_per_hour=1, trusted_proxy=1) as (client, app):
        await post_and_finish(client, app, "a", **{"X-Forwarded-For": "1.1.1.1"})
        resp = await post(client, "b", **{"X-Forwarded-For": "5.5.5.5, 1.1.1.1"})
    assert resp.status_code == 429


# --- replays that cost nothing -------------------------------------------------------------


async def test_a_rerun_the_cache_will_answer_is_not_counted(limited):
    async with limited(rate_limit_per_hour=2) as (client, app):
        assert (await post_and_finish(client, app, Q)).status_code == 201  # counts: 1 of 2
        for _ in range(4):  # identical, clean, finished: free
            assert (await post_and_finish(client, app, Q)).status_code == 201
        assert (await post_and_finish(client, app, "another")).status_code == 201  # 2 of 2
        assert (await post(client, "a third")).status_code == 429


async def test_a_different_mode_or_round_count_is_not_a_rerun(limited):
    async with limited(rate_limit_per_hour=1) as (client, app):
        await post_and_finish(client, app, Q)
        other_rounds = await client.post("/api/debates", json={"question": Q, "rounds": 1})
        assert other_rounds.status_code == 429


async def test_a_rerun_of_a_debate_with_errors_or_fallbacks_is_counted(limited):
    async with limited(rate_limit_per_hour=1) as (client, app):
        resp = await post_and_finish(client, app, Q)
        from app.db.models import DebateEventRow

        with Session(app.state.service.engine) as s:
            s.add(
                DebateEventRow(
                    debate_id=resp.json()["id"], seq=999, type="error", data={"message": "x"}
                )
            )
            s.commit()
        assert (await post(client, Q)).status_code == 429


async def test_reruns_are_not_free_when_the_cache_is_off(limited):
    async with limited(rate_limit_per_hour=1, cache_enabled=False) as (client, app):
        await post_and_finish(client, app, Q)
        assert (await post(client, Q)).status_code == 429


async def test_a_changed_lineup_or_prompt_set_invalidates_the_rerun_exemption(limited):
    async with limited(rate_limit_per_hour=1) as (client, app):
        await post_and_finish(client, app, Q)
        app.state.service.agents.judge.persona_prompt += " changed"
        assert (await post(client, Q)).status_code == 429


# --- global daily cap ----------------------------------------------------------------------


async def test_global_cap_counts_real_debates_and_ignores_zero_call_ones(limited, clock):
    async with limited(global_daily_cap=2, rate_limit_per_hour=100) as (client, app):
        add_debate(app, api_calls=0)  # answered entirely from the cache: free
        add_debate(app, api_calls=4)
        assert (await post_and_finish(client, app, "a")).status_code == 201  # mock: 0 calls, free
        add_debate(app, api_calls=9)
        resp = await post(client, "b")
    assert resp.status_code == 429
    body = resp.json()
    assert body["scope"] == "global_day" and "quota" in body["message"]
    assert body["retry_after_s"] == seconds_until_utc_midnight(clock.now)
    assert resp.headers["Retry-After"] == str(body["retry_after_s"])


async def test_global_cap_counts_running_and_unfinished_debates(limited):
    async with limited(global_daily_cap=1) as (client, app):
        add_debate(app, status="running", api_calls=0)
        assert (await post(client, "a")).status_code == 429


async def test_global_cap_only_counts_today(limited, clock):
    async with limited(global_daily_cap=1) as (client, app):
        yesterday = datetime.fromtimestamp(clock.now - 86400 * 2, UTC)
        add_debate(app, created_at=yesterday)
        assert (await post_and_finish(client, app, "a")).status_code == 201


async def test_global_cap_does_not_apply_to_reruns_and_is_off_at_zero(limited):
    async with limited(global_daily_cap=1, rate_limit_per_hour=100) as (client, app):
        assert (await post_and_finish(client, app, Q)).status_code == 201
        add_debate(app, api_calls=3)  # the cap is now reached
        assert (await post(client, "new question")).status_code == 429
        assert (await post_and_finish(client, app, Q)).status_code == 201  # free rerun
    async with limited(global_daily_cap=0, rate_limit_per_hour=100) as (client, app):
        for _ in range(3):
            add_debate(app, api_calls=3)
        assert (await post_and_finish(client, app, "x")).status_code == 201


async def test_a_refused_request_does_not_use_up_the_ip_allowance(limited):
    async with limited(global_daily_cap=1, rate_limit_per_hour=1) as (client, app):
        add_debate(app, api_calls=3)
        assert (await post(client, "a")).json()["scope"] == "global_day"
        # Had the refused request been counted, this would report ip_hour instead.
        assert (await post(client, "b")).json()["scope"] == "global_day"


# --- concurrency cap -----------------------------------------------------------------------


async def test_busy_when_too_many_debates_run_and_free_again_afterwards(limited):
    async with limited(
        demo_factory(delay_s=0.05), max_concurrent_debates=1, rate_limit_per_hour=2
    ) as (client, app):
        first = await post(client, "a")
        assert first.status_code == 201
        busy = await post(client, "b")
        assert busy.status_code == 429
        body = busy.json()
        assert body["scope"] == "busy" and body["retry_after_s"] == 30
        assert busy.headers["Retry-After"] == "30"
        await wait_until(lambda: not app.state.service._channels)
        # The refused request cost nothing: one allowance is still left.
        assert (await post_and_finish(client, app, "c")).status_code == 201
        assert (await post(client, "d")).json()["scope"] == "ip_hour"


async def test_busy_cap_works_with_rate_limiting_off(make_client):
    async with make_client(demo_factory(delay_s=0.05), max_concurrent_debates=1) as (client, app):
        assert (await post(client, "a")).status_code == 201
        assert (await post(client, "b")).json()["scope"] == "busy"
        await wait_until(lambda: not app.state.service._channels)
        assert (await post(client, "c")).status_code == 201
        await wait_until(lambda: not app.state.service._channels)
