"""OddsPapi service with budget enforcement, fixture synchronization, and horizon market comparisons."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from betting_app.ml.calibration.conformal_contract import conformal_bounds_for_side


from betting_app.core.db import get_session
from betting_app.core.matching import normalize_team_name
from betting_app.models.match import CanonicalMatch
from betting_app.models.odds import OddsSnapshot
from betting_app.models.oddspapi import OddspapiFixtureMapping, OddspapiRequestLog
from betting_app.models.prediction import CanonicalPrediction
from betting_app.services.odds_service import get_or_create_bookmaker

logger = logging.getLogger(__name__)

ODDSPAPI_API_BASE = "https://api.oddspapi.io/v4"
DEFAULT_MONTHLY_LIMIT = 250
DEFAULT_DAILY_LIMIT = 8
LOL_SPORT_ID = 18
WINNER_MARKET_ID = "181"
OUTCOME_TEAM_1 = "181"
OUTCOME_TEAM_2 = "182"

PRIORITY_LEAGUES: set[str] = {
    "lck",
    "lpl",
    "lec",
    "lcs",
    "worlds",
    "msi",
    "lfl",
    "lck challengers",
    "lck cl",
}


class OddsPapiError(RuntimeError):
    """Base exception for OddsPapi service failures."""


class OddsPapiBudgetExhaustedError(OddsPapiError):
    """Raised when monthly or daily request allowance has been exhausted."""


class OddsPapiHTTPError(OddsPapiError):
    """Raised on remote HTTP errors with status and response diagnostics."""

    def __init__(self, path: str, status: int, body: str) -> None:
        self.path = path
        self.status = status
        self.body = body
        self.retry_after_seconds: float | None = None
        try:
            retry_after = json.loads(body).get("error", {}).get("retryAfter")
            if retry_after:
                self.retry_after_seconds = float(str(retry_after).split()[0])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
        super().__init__(f"OddsPapi {path} returned HTTP {status}: {body[:300]}")


def parse_utc(value: str | datetime) -> datetime:
    """Parse string or datetime to timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class OddsPapiBudgetGuard:
    """Enforces strict daily and monthly quota boundaries backed by oddspapi_request_logs."""

    def __init__(
        self,
        monthly_limit: int = DEFAULT_MONTHLY_LIMIT,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
        monthly_window_days: int = 30,
        daily_window_hours: int = 24,
    ) -> None:
        self.monthly_limit = int(os.getenv("ODDSPAPI_MONTHLY_LIMIT", monthly_limit))
        self.daily_limit = int(os.getenv("ODDSPAPI_DAILY_LIMIT", daily_limit))
        self.monthly_window_days = monthly_window_days
        self.daily_window_hours = daily_window_hours

    def check_budget(self, session: Session) -> tuple[bool, str, dict[str, int]]:
        """Verify request capacity against persisted audit logs."""
        now = datetime.now(UTC)
        monthly_since = now - timedelta(days=self.monthly_window_days)
        daily_since = now - timedelta(hours=self.daily_window_hours)

        monthly_used = (
            session.scalar(
                select(func.count(OddspapiRequestLog.id)).where(
                    OddspapiRequestLog.created_at >= monthly_since
                )
            )
            or 0
        )

        daily_used = (
            session.scalar(
                select(func.count(OddspapiRequestLog.id)).where(
                    OddspapiRequestLog.created_at >= daily_since
                )
            )
            or 0
        )

        stats = {
            "monthly_used": int(monthly_used),
            "monthly_limit": self.monthly_limit,
            "monthly_remaining": max(0, self.monthly_limit - int(monthly_used)),
            "daily_used": int(daily_used),
            "daily_limit": self.daily_limit,
            "daily_remaining": max(0, self.daily_limit - int(daily_used)),
        }

        if monthly_used >= self.monthly_limit:
            return (
                False,
                f"OddsPapi monthly quota reached ({monthly_used}/{self.monthly_limit})",
                stats,
            )

        if daily_used >= self.daily_limit:
            return (
                False,
                f"OddsPapi daily cap reached ({daily_used}/{self.daily_limit})",
                stats,
            )

        return True, "OK", stats

    def record_request(
        self,
        session: Session,
        endpoint: str,
        fixture_id: str | None,
        status_code: int,
        response_time_ms: int | None = None,
    ) -> OddspapiRequestLog:
        """Record an API request in the audit log."""
        log_entry = OddspapiRequestLog(
            endpoint=endpoint,
            fixture_id=fixture_id,
            status_code=status_code,
            response_time_ms=response_time_ms,
            created_at=datetime.now(UTC),
        )
        session.add(log_entry)
        session.commit()
        return log_entry


class OddsPapiClient:
    """HTTP client for OddsPapi with budget tracking and diagnostic error reporting."""

    def __init__(
        self,
        api_key: str | None = None,
        budget_guard: OddsPapiBudgetGuard | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.api_key = api_key or os.getenv("ODDSPAPI_API_KEY", "")
        self.budget_guard = budget_guard or OddsPapiBudgetGuard()
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        session: Session | None = None,
        fixture_id: str | None = None,
    ) -> Any:
        """Perform a metered GET request against OddsPapi."""
        if not self.is_configured():
            raise OddsPapiError("OddsPapi API key is not configured (set ODDSPAPI_API_KEY).")

        sess = session or get_session()
        own_session = session is None
        try:
            allowed, reason, stats = self.budget_guard.check_budget(sess)
            if not allowed:
                raise OddsPapiBudgetExhaustedError(reason)

            query_params = dict(params or {})
            query_params["apiKey"] = self.api_key

            url = f"{ODDSPAPI_API_BASE}{path}?{urlencode(query_params)}"
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "EnsembleLegends OddsPapi Client/1.0",
                },
            )

            start_t = time.perf_counter()
            status_code = 0
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                    status_code = response.status
                    body = response.read().decode("utf-8")
                    duration_ms = int((time.perf_counter() - start_t) * 1000)
                    self.budget_guard.record_request(
                        sess, path, fixture_id, status_code, duration_ms
                    )
                    return json.loads(body)
            except HTTPError as error:
                status_code = error.code
                duration_ms = int((time.perf_counter() - start_t) * 1000)
                body = error.read().decode("utf-8", errors="replace")
                self.budget_guard.record_request(
                    sess, path, fixture_id, status_code, duration_ms
                )
                raise OddsPapiHTTPError(path, status_code, body) from error
            except URLError as error:
                raise OddsPapiError(f"OddsPapi connection error: {error.reason}") from error
        finally:
            if own_session:
                sess.close()


def extract_winner_odds(
    payload: dict[str, Any],
    bookmaker_slug: str = "pinnacle",
    cutoff_time: datetime | None = None,
) -> tuple[float, float, str] | None:
    """Extract (price_outcome_1, price_outcome_2, quote_time_iso) for winner market (181).

    Supports both /v4/odds (live board) and /v4/historical-odds (timeline) structures.
    """
    books = payload.get("bookmakerOdds") or payload.get("bookmakers") or {}
    book_data = books.get(bookmaker_slug)
    if not isinstance(book_data, dict):
        return None

    markets = book_data.get("markets") or {}
    market = markets.get(WINNER_MARKET_ID) or {}
    outcomes = market.get("outcomes") or {}
    out1 = outcomes.get(OUTCOME_TEAM_1) or {}
    out2 = outcomes.get(OUTCOME_TEAM_2) or {}

    def get_price_and_time(outcome: dict[str, Any]) -> tuple[float, str] | None:
        players = outcome.get("players") or {}
        player_0 = players.get("0")
        if isinstance(player_0, dict):
            price = player_0.get("price")
            is_active = player_0.get("active", True)
            if price is not None and is_active:
                ts = player_0.get("createdAt") or datetime.now(UTC).isoformat()
                return float(price), str(ts)
            return None
        elif isinstance(player_0, list):
            valid = []
            for item in player_0:
                if not isinstance(item, dict):
                    continue
                if item.get("price") is None or not item.get("active", True):
                    continue
                created_at_str = item.get("createdAt")
                if not created_at_str:
                    continue
                dt = parse_utc(created_at_str)
                if cutoff_time is not None and dt > cutoff_time:
                    continue
                valid.append((dt, float(item["price"]), created_at_str))
            if not valid:
                return None
            valid.sort(key=lambda x: x[0])
            latest = valid[-1]
            return latest[1], latest[2]
        return None

    res1 = get_price_and_time(out1)
    res2 = get_price_and_time(out2)
    if not res1 or not res2:
        return None

    price_1, ts1 = res1
    price_2, ts2 = res2
    if price_1 <= 1.0 or price_2 <= 1.0:
        return None

    latest_ts = max(ts1, ts2)
    return price_1, price_2, latest_ts


def sync_oddspapi_fixtures(
    session: Session | None = None,
    days_ahead: int = 7,
    client: OddsPapiClient | None = None,
) -> dict[str, Any]:
    """Fetch upcoming LoL fixtures and match them to canonical_matches.

    Costs exactly 1 request to /v4/fixtures.
    """
    api_client = client or OddsPapiClient()
    if not api_client.is_configured():
        return {"status": "skipped", "reason": "ODDSPAPI_API_KEY not configured"}

    sess = session or get_session()
    own_session = session is None
    try:
        now = datetime.now(UTC)
        to_date = now + timedelta(days=days_ahead)

        payload = api_client.get(
            "/fixtures",
            {
                "sportId": LOL_SPORT_ID,
                "from": now.strftime("%Y-%m-%d"),
                "to": to_date.strftime("%Y-%m-%d"),
            },
            session=sess,
        )

        if not isinstance(payload, list):
            return {"status": "error", "error": f"Unexpected payload type {type(payload).__name__}"}

        # Load upcoming canonical matches in the corresponding window
        canonical_matches = sess.scalars(
            select(CanonicalMatch).where(
                CanonicalMatch.status.in_(("upcoming", "active", "pending"))
            )
        ).all()

        canonical_by_pair: dict[frozenset[str], list[CanonicalMatch]] = {}
        for cm in canonical_matches:
            if not cm.team_a_name or not cm.team_b_name:
                continue
            norm_a = normalize_team_name(cm.team_a_name)
            norm_b = normalize_team_name(cm.team_b_name)
            pair = frozenset((norm_a, norm_b))
            canonical_by_pair.setdefault(pair, []).append(cm)

        synced_count = 0
        mapped_count = 0

        for fixture in payload:
            fixture_id = str(fixture.get("fixtureId") or "")
            if not fixture_id:
                continue

            raw_team_1 = str(fixture.get("participant1Name") or "")
            raw_team_2 = str(fixture.get("participant2Name") or "")
            if not raw_team_1 or not raw_team_2:
                continue

            norm_1 = normalize_team_name(raw_team_1)
            norm_2 = normalize_team_name(raw_team_2)
            pair = frozenset((norm_1, norm_2))

            start_time_str = fixture.get("startTime")
            fixture_start = parse_utc(start_time_str) if start_time_str else None

            # Attempt to resolve canonical match
            canonical_match_id: int | None = None
            team_1_is_a: int | None = None

            candidates = canonical_by_pair.get(pair, [])
            if candidates and fixture_start:
                valid_candidates = []
                for candidate in candidates:
                    if not candidate.start_time_normalized:
                        continue
                    c_start = parse_utc(candidate.start_time_normalized)
                    if abs((c_start - fixture_start).total_seconds()) <= 43200:  # 12h
                        valid_candidates.append((abs((c_start - fixture_start).total_seconds()), candidate))

                if len(valid_candidates) == 1:
                    matched_cm = valid_candidates[0][1]
                    canonical_match_id = matched_cm.id
                    norm_a = normalize_team_name(matched_cm.team_a_name)
                    team_1_is_a = 1 if norm_1 == norm_a else 0
                    mapped_count += 1

            existing = sess.scalar(
                select(OddspapiFixtureMapping).where(
                    OddspapiFixtureMapping.fixture_id == fixture_id
                )
            )

            if existing:
                if canonical_match_id is not None:
                    existing.canonical_match_id = canonical_match_id
                    existing.provider_team_1_is_a = team_1_is_a
                existing.has_odds = 1 if fixture.get("hasOdds") else 0
                existing.last_synced_at = now
            else:
                mapping = OddspapiFixtureMapping(
                    fixture_id=fixture_id,
                    canonical_match_id=canonical_match_id,
                    sport_id=LOL_SPORT_ID,
                    league=str(fixture.get("tournamentName") or fixture.get("leagueName") or ""),
                    provider_team_1=raw_team_1,
                    provider_team_2=raw_team_2,
                    provider_team_1_is_a=team_1_is_a,
                    start_time=fixture_start,
                    has_odds=1 if fixture.get("hasOdds") else 0,
                    last_synced_at=now,
                )
                sess.add(mapping)

            synced_count += 1

        sess.commit()
        return {
            "status": "success",
            "fixtures_synced": synced_count,
            "mapped_to_canonical": mapped_count,
        }
    except OddsPapiBudgetExhaustedError as err:
        logger.warning(f"OddsPapi fixture sync blocked by budget: {err}")
        return {"status": "budget_exhausted", "error": str(err)}
    finally:
        if own_session:
            sess.close()


def fetch_pinnacle_horizon_odds(
    session: Session | None = None,
    target_horizon_hours: float = 6.0,
    tolerance_hours: float = 1.0,
    max_requests: int = 4,
    client: OddsPapiClient | None = None,
) -> dict[str, Any]:
    """Fetch Pinnacle odds for matches in the target horizon window (e.g. T−6h).

    Only queries matches with an existing OddspapiFixtureMapping that lack a recent Pinnacle quote.
    """
    api_client = client or OddsPapiClient()
    if not api_client.is_configured():
        return {"status": "skipped", "reason": "ODDSPAPI_API_KEY not configured"}

    sess = session or get_session()
    own_session = session is None
    try:
        now = datetime.now(UTC)
        window_start = now + timedelta(hours=target_horizon_hours - tolerance_hours)
        window_end = now + timedelta(hours=target_horizon_hours + tolerance_hours)

        pinnacle_id = get_or_create_bookmaker("pinnacle")

        # Find upcoming matches mapped to OddsPapi
        mappings = sess.scalars(
            select(OddspapiFixtureMapping).where(
                OddspapiFixtureMapping.canonical_match_id.is_not(None),
                OddspapiFixtureMapping.start_time >= window_start,
                OddspapiFixtureMapping.start_time <= window_end,
                OddspapiFixtureMapping.has_odds == 1,
            )
        ).all()

        if not mappings:
            return {"status": "success", "fetched": 0, "saved": 0, "candidates": 0}

        # Filter out matches that already have a Pinnacle quote within the last 2 hours
        eligible: list[OddspapiFixtureMapping] = []
        for mapping in mappings:
            cm_id = mapping.canonical_match_id
            assert cm_id is not None
            recent_quote = sess.scalar(
                select(OddsSnapshot.id).where(
                    OddsSnapshot.canonical_match_id == cm_id,
                    OddsSnapshot.bookmaker_id == pinnacle_id,
                    OddsSnapshot.scraped_at >= (now - timedelta(hours=2)).isoformat(),
                )
            )
            if not recent_quote:
                eligible.append(mapping)

        # Sort eligible matches: priority leagues first, then earliest start
        def league_priority(m: OddspapiFixtureMapping) -> tuple[int, datetime]:
            league_str = (m.league or "").lower()
            is_priority = 0 if any(p in league_str for p in PRIORITY_LEAGUES) else 1
            start = m.start_time or now
            return is_priority, start

        eligible.sort(key=league_priority)
        to_fetch = eligible[:max_requests]

        fetched_count = 0
        saved_count = 0

        for mapping in to_fetch:
            cm_id = mapping.canonical_match_id
            assert cm_id is not None

            # Verify budget before each individual call
            allowed, reason, _ = api_client.budget_guard.check_budget(sess)
            if not allowed:
                logger.warning(f"Stopping horizon odds fetch: {reason}")
                break

            try:
                payload = api_client.get(
                    "/odds",
                    {"fixtureId": mapping.fixture_id},
                    session=sess,
                    fixture_id=mapping.fixture_id,
                )
            except OddsPapiHTTPError as err:
                logger.error(f"Failed to fetch odds for fixture {mapping.fixture_id}: {err}")
                continue
            except OddsPapiBudgetExhaustedError:
                break

            fetched_count += 1
            cm = sess.get(CanonicalMatch, cm_id)
            if not cm:
                continue

            extracted = extract_winner_odds(payload, bookmaker_slug="pinnacle")
            if not extracted:
                continue

            price_1, price_2, quote_ts = extracted

            # Align sides
            provider_is_a = mapping.provider_team_1_is_a
            if provider_is_a is None or provider_is_a == 1:
                odds_a, odds_b = price_1, price_2
            else:
                odds_a, odds_b = price_2, price_1

            snapshot = OddsSnapshot(
                bookmaker_id=pinnacle_id,
                canonical_match_id=cm.id,
                market_type="match_winner",
                raw_team_a=cm.team_a_name,
                raw_team_b=cm.team_b_name,
                odds_a=odds_a,
                odds_b=odds_b,
                is_live=0,
                scraped_at=quote_ts,
                source_url=f"oddspapi://v4/odds/{mapping.fixture_id}",
            )
            sess.add(snapshot)
            saved_count += 1

        sess.commit()
        return {
            "status": "success",
            "candidates": len(eligible),
            "fetched": fetched_count,
            "saved": saved_count,
        }
    finally:
        if own_session:
            sess.close()


def compare_match_market(
    canonical_match_id: int,
    session: Session | None = None,
    horizon_hours: float = 6.0,
    tolerance_hours: float = 1.5,
) -> dict[str, Any] | None:
    """Compare Pinnacle consensus line with Polish bookmakers and model probability."""
    sess = session or get_session()
    own_session = session is None
    try:
        cm = sess.get(CanonicalMatch, canonical_match_id)
        if not cm or not cm.start_time_normalized:
            return None

        match_start = parse_utc(cm.start_time_normalized)
        target_time = match_start - timedelta(hours=horizon_hours)
        window_start = (target_time - timedelta(hours=tolerance_hours)).isoformat()
        window_end = target_time.isoformat()

        # Load snapshots for this match
        from betting_app.models.bookmaker import Bookmaker

        snapshots = (
            sess.execute(
                select(OddsSnapshot, Bookmaker.name)
                .join(Bookmaker, Bookmaker.id == OddsSnapshot.bookmaker_id)
                .where(
                    OddsSnapshot.canonical_match_id == canonical_match_id,
                    OddsSnapshot.market_type == "match_winner",
                    OddsSnapshot.odds_a.is_not(None),
                    OddsSnapshot.odds_b.is_not(None),
                    OddsSnapshot.odds_a > 1.0,
                    OddsSnapshot.odds_b > 1.0,
                    OddsSnapshot.scraped_at <= window_end,
                )
                .order_by(OddsSnapshot.scraped_at.desc())
            )
            .all()
        )

        # Select latest pre-target snapshot per bookmaker
        latest_by_bookmaker: dict[str, Any] = {}
        for snap, book_name in snapshots:
            if book_name not in latest_by_bookmaker:
                latest_by_bookmaker[book_name] = snap

        pinnacle_snap = latest_by_bookmaker.get("pinnacle")
        pinnacle_prob_a: float | None = None
        pinnacle_margin: float | None = None
        if pinnacle_snap:
            inv_a = 1.0 / float(pinnacle_snap.odds_a)
            inv_b = 1.0 / float(pinnacle_snap.odds_b)
            pinnacle_margin = inv_a + inv_b - 1.0
            pinnacle_prob_a = inv_a / (inv_a + inv_b)

        # Load latest model prediction
        pred = sess.scalars(
            select(CanonicalPrediction)
            .where(CanonicalPrediction.canonical_match_id == canonical_match_id)
            .order_by(CanonicalPrediction.predicted_at.desc())
        ).first()

        model_prob_a = float(pred.prob_a) if pred and pred.prob_a is not None else None
        conformal_a = (
            conformal_bounds_for_side(pred.diagnostics_json, "a")
            if pred is not None
            else None
        )
        conformal_b = (
            conformal_bounds_for_side(pred.diagnostics_json, "b")
            if pred is not None
            else None
        )

        bookmakers_comparison: list[dict[str, Any]] = []
        for name, snap in sorted(latest_by_bookmaker.items()):
            odds_a = float(snap.odds_a)
            odds_b = float(snap.odds_b)
            inv_a = 1.0 / odds_a
            inv_b = 1.0 / odds_b
            margin = inv_a + inv_b - 1.0
            novig_a = inv_a / (inv_a + inv_b)

            delta_pin = round(novig_a - pinnacle_prob_a, 4) if pinnacle_prob_a is not None else None

            # Calculate EV with 12% turnover tax for Polish bookmakers
            ev_a = None
            ev_b = None
            ev_conf_a = None
            ev_conf_b = None
            is_conf_a = False
            is_conf_b = False

            if model_prob_a is not None:
                ev_a = round(model_prob_a * (odds_a * 0.88) - 1.0, 4)
                ev_b = round((1.0 - model_prob_a) * (odds_b * 0.88) - 1.0, 4)

                if (
                    conformal_a is not None
                    and conformal_b is not None
                    and conformal_a[1] - conformal_a[0] <= 0.08
                    and conformal_b[1] - conformal_b[0] <= 0.08
                ):
                    ev_conf_a = round(
                        conformal_a[0] * (odds_a * 0.88) - 1.0, 4
                    )
                    ev_conf_b = round(
                        conformal_b[0] * (odds_b * 0.88) - 1.0, 4
                    )
                    is_conf_a = ev_conf_a > 0.0
                    is_conf_b = ev_conf_b > 0.0

            bookmakers_comparison.append(
                {
                    "bookmaker": name,
                    "odds_a": odds_a,
                    "odds_b": odds_b,
                    "novig_prob_a": round(novig_a, 4),
                    "margin": round(margin, 4),
                    "scraped_at": snap.scraped_at,
                    "delta_to_pinnacle": delta_pin,
                    "ev_team_a_tax12": ev_a,
                    "ev_team_b_tax12": ev_b,
                    "ev_conformal_low_a": ev_conf_a,
                    "ev_conformal_low_b": ev_conf_b,
                    "is_conformal_value_a": is_conf_a,
                    "is_conformal_value_b": is_conf_b,
                }
            )

        return {
            "canonical_match_id": canonical_match_id,
            "team_a": cm.team_a_name,
            "team_b": cm.team_b_name,
            "league": cm.league,
            "match_start_at": cm.start_time_normalized,
            "target_horizon_hours": horizon_hours,
            "model_prob_a": model_prob_a,
            "pinnacle_novig_prob_a": round(pinnacle_prob_a, 4) if pinnacle_prob_a is not None else None,
            "pinnacle_margin": round(pinnacle_margin, 4) if pinnacle_margin is not None else None,
            "bookmakers": bookmakers_comparison,
        }
    finally:
        if own_session:
            sess.close()
