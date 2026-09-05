"""Service for automated Value Bet alerting via Discord Webhooks and Telegram."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session
from betting_app.models.alerts import AlertConfig, ValueAlertLog
from betting_app.api.deps import query_df, query_one
from betting_app.core.config import load_config

logger = logging.getLogger(__name__)

DEFAULT_MIN_EV = 0.05
DEFAULT_MIN_ODDS = 1.25
DEFAULT_MAX_ODDS = 12.0
DEFAULT_COOLDOWN_HOURS = 6.0


def get_or_create_alert_config(db: Session) -> AlertConfig:
    """Get persistent alert configuration from DB or initialize from environment defaults."""
    cfg = db.query(AlertConfig).filter(AlertConfig.id == 1).first()
    if not cfg:
        app_cfg = load_config()
        cfg = AlertConfig(
            id=1,
            is_enabled=True,
            min_ev=float(os.getenv("ALERT_MIN_EV", str(DEFAULT_MIN_EV))),
            min_odds=float(os.getenv("ALERT_MIN_ODDS", str(DEFAULT_MIN_ODDS))),
            max_odds=float(os.getenv("ALERT_MAX_ODDS", str(DEFAULT_MAX_ODDS))),
            cooldown_hours=float(os.getenv("ALERT_COOLDOWN_HOURS", str(DEFAULT_COOLDOWN_HOURS))),
            discord_enabled=True,
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL"),
            telegram_enabled=True,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def update_alert_config(
    db: Session,
    *,
    is_enabled: Optional[bool] = None,
    min_ev: Optional[float] = None,
    min_odds: Optional[float] = None,
    max_odds: Optional[float] = None,
    cooldown_hours: Optional[float] = None,
    discord_enabled: Optional[bool] = None,
    discord_webhook_url: Optional[str] = None,
    telegram_enabled: Optional[bool] = None,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
) -> AlertConfig:
    """Update alert configuration parameters."""
    cfg = get_or_create_alert_config(db)
    if is_enabled is not None:
        cfg.is_enabled = is_enabled
    if min_ev is not None:
        cfg.min_ev = min_ev
    if min_odds is not None:
        cfg.min_odds = min_odds
    if max_odds is not None:
        cfg.max_odds = max_odds
    if cooldown_hours is not None:
        cfg.cooldown_hours = cooldown_hours
    if discord_enabled is not None:
        cfg.discord_enabled = discord_enabled
    if discord_webhook_url is not None:
        cfg.discord_webhook_url = discord_webhook_url.strip() if discord_webhook_url else None
    if telegram_enabled is not None:
        cfg.telegram_enabled = telegram_enabled
    if telegram_bot_token is not None:
        cfg.telegram_bot_token = telegram_bot_token.strip() if telegram_bot_token else None
    if telegram_chat_id is not None:
        cfg.telegram_chat_id = telegram_chat_id.strip() if telegram_chat_id else None

    cfg.updated_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(cfg)
    return cfg


def build_discord_embed(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Format a Discord Rich Embed payload for a Value Bet."""
    match_label = signal.get("match_label", "League of Legends Match")
    league = signal.get("league") or "LoL Esports"
    team_name = signal.get("team_name", "Unknown Team")
    side = (signal.get("side") or "").upper()
    bookmaker = signal.get("bookmaker_name", "Bukmacher")
    odds = float(signal.get("odds") or 0.0)
    ev = float(signal.get("ev") or 0.0)
    model_prob = float(signal.get("model_prob") or 0.0)
    market_prob = float(signal.get("market_prob") or 0.0)
    stake_pct = float(signal.get("suggested_stake") or 0.0)
    match_start = signal.get("match_start_at") or "Wkrótce"

    # Color: Bright Green for strong EV (>10%), Cyan for 5-10%
    color = 0x10B981 if ev >= 0.10 else 0x38BDF8

    fields = [
        {"name": "🎯 Typowana Drużyna", "value": f"**{team_name}** ({side})", "inline": True},
        {"name": "🏢 Bukmacher", "value": f"**{bookmaker}**", "inline": True},
        {"name": "📈 Kurs", "value": f"**{odds:.2f}**", "inline": True},
        {"name": "💰 EV (po podatku 12%)", "value": f"**+{ev * 100:.1f}%**", "inline": True},
        {"name": "📊 Model vs Rynek", "value": f"Model: `{model_prob * 100:.1f}%`\nRynek: `{market_prob * 100:.1f}%`", "inline": True},
        {"name": "💵 Sugerowana Stawka", "value": f"`{stake_pct:.1f}%` bankrolla", "inline": True},
        {"name": "⏰ Początek Meczu", "value": f"{match_start}", "inline": False},
    ]

    return {
        "title": f"🔥 VALUE BET: {match_label}",
        "description": f"Zidentyfikowano dodatnią wartość oczekiwaną w lidze **{league}**.",
        "color": color,
        "fields": fields,
        "footer": {"text": "EnsembleLegends • LoL Value Bet Intelligence"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_telegram_html(signal: Dict[str, Any]) -> str:
    """Format a Telegram HTML message for a Value Bet."""
    match_label = signal.get("match_label", "League of Legends Match")
    league = signal.get("league") or "LoL Esports"
    team_name = signal.get("team_name", "Unknown Team")
    side = (signal.get("side") or "").upper()
    bookmaker = signal.get("bookmaker_name", "Bukmacher")
    odds = float(signal.get("odds") or 0.0)
    ev = float(signal.get("ev") or 0.0)
    model_prob = float(signal.get("model_prob") or 0.0)
    market_prob = float(signal.get("market_prob") or 0.0)
    stake_pct = float(signal.get("suggested_stake") or 0.0)
    match_start = signal.get("match_start_at") or "Wkrótce"

    return (
        f"🔥 <b>VALUE BET ALERT</b>\n\n"
        f"🏆 <b>Mecz:</b> {match_label} (<i>{league}</i>)\n"
        f"🎯 <b>Typ:</b> <b>{team_name}</b> [Strona {side}]\n"
        f"🏢 <b>Bukmacher:</b> <b>{bookmaker}</b>\n"
        f"📈 <b>Kurs:</b> <b>{odds:.2f}</b>\n"
        f"💰 <b>EV (po podatku 12%):</b> <b>+{ev * 100:.1f}%</b>\n"
        f"📊 <b>Prawdopodobieństwo:</b> Model: {model_prob * 100:.1f}% | Rynek: {market_prob * 100:.1f}%\n"
        f"💵 <b>Sugerowana stawka (Kelly):</b> {stake_pct:.1f}% bankrolla\n"
        f"⏰ <b>Start meczu:</b> {match_start}\n\n"
        f"⚡ <i>EnsembleLegends Intelligence</i>"
    )


def send_discord_notification(webhook_url: str, embed: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Send a notification to Discord webhook. Returns (success, error_message)."""
    if not webhook_url:
        return False, "Brak skonfigurowanego URL Discord Webhook"
    try:
        payload = {
            "username": "EnsembleLegends Alerts",
            "avatar_url": "https://raw.githubusercontent.com/FortAwesome/Font-Awesome/master/svgs/solid/fire.svg",
            "embeds": [embed],
        }
        res = requests.post(webhook_url, json=payload, timeout=8)
        if 200 <= res.status_code < 300:
            return True, None
        return False, f"Discord HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        logger.warning("Failed to send Discord webhook alert: %s", e)
        return False, str(e)


def send_telegram_notification(token: str, chat_id: str, html_text: str) -> tuple[bool, Optional[str]]:
    """Send a notification to Telegram chat. Returns (success, error_message)."""
    if not token or not chat_id:
        return False, "Brak skonfigurowanego tokenu lub Chat ID Telegrama"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        res = requests.post(url, json=payload, timeout=8)
        if 200 <= res.status_code < 300:
            return True, None
        return False, f"Telegram HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        logger.warning("Failed to send Telegram alert: %s", e)
        return False, str(e)


def is_alert_on_cooldown(
    db: Session,
    canonical_match_id: Optional[int],
    bookmaker_name: Optional[str],
    side: Optional[str],
    new_odds: float,
    new_ev: float,
    cooldown_hours: float,
) -> bool:
    """Check whether an alert for this exact match, bookmaker, and side was sent recently."""
    if not canonical_match_id or not bookmaker_name or not side:
        return False

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat()

    row = query_one(
        db,
        """
        SELECT odds, ev
        FROM value_alert_logs
        WHERE canonical_match_id = :mid
          AND bookmaker_name = :bname
          AND side = :side
          AND status IN ('sent', 'simulated')
          AND created_at >= :cutoff
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"mid": canonical_match_id, "bname": bookmaker_name, "side": side, "cutoff": cutoff},
    )
    if not row:
        return False

    old_odds = float(row.get("odds") or 0.0)
    old_ev = float(row.get("ev") or 0.0)

    # If odds increased by at least 0.05 or EV grew by at least 2.0 percentage points, allow re-alerting!
    if new_odds >= old_odds + 0.05 or new_ev >= old_ev + 0.02:
        return False

    return True


def scan_and_dispatch_ev_alerts(db: Session, force_dry_run: bool = False) -> Dict[str, Any]:
    """Scan the database for valid upcoming EV+ signals and dispatch notifications."""
    cfg = get_or_create_alert_config(db)
    if not cfg.is_enabled and not force_dry_run:
        return {
            "dispatched": 0,
            "skipped": 0,
            "failed": 0,
            "alerts": [],
            "message": "Powiadomienia Value Bet są wyłączone w konfiguracji.",
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    min_ev = cfg.min_ev
    min_odds = cfg.min_odds
    max_odds = cfg.max_odds or 999.0
    cooldown_hours = cfg.cooldown_hours

    # Fetch active new EV signals for matches starting in the future
    sql = """
        SELECT
            mes.id AS signal_id,
            mes.canonical_match_id,
            mes.side,
            mes.odds,
            mes.model_prob,
            mes.market_prob,
            mes.ev,
            mes.stake_suggestion,
            cm.team_a_name,
            cm.team_b_name,
            cm.league,
            cm.start_time_normalized,
            b.name AS bookmaker_name
        FROM model_ev_signals mes
        JOIN canonical_matches cm ON cm.id = mes.canonical_match_id
        JOIN bookmakers b ON b.id = mes.bookmaker_id
        WHERE mes.status = 'new'
          AND mes.ev >= :min_ev
          AND mes.odds >= :min_odds
          AND mes.odds <= :max_odds
          AND (cm.start_time_normalized IS NULL OR cm.start_time_normalized > :now_iso)
        ORDER BY mes.ev DESC
        LIMIT 25
    """

    rows = query_df(
        db,
        sql,
        {"min_ev": min_ev, "min_odds": min_odds, "max_odds": max_odds, "now_iso": now_iso},
    )

    dispatched = 0
    skipped = 0
    failed = 0
    alert_results = []

    # Check which channels are active
    discord_url = cfg.discord_webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    tg_token = cfg.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = cfg.telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")

    can_discord = bool(cfg.discord_enabled and discord_url)
    can_telegram = bool(cfg.telegram_enabled and tg_token and tg_chat)

    for row in rows:
        side = str(row.get("side") or "").lower()
        team_a = row.get("team_a_name") or "Team A"
        team_b = row.get("team_b_name") or "Team B"
        team_name = team_a if side == "a" else team_b
        match_label = f"{team_a} vs {team_b}"
        bookmaker_name = row.get("bookmaker_name") or "Bukmacher"
        odds = float(row.get("odds") or 0.0)
        ev = float(row.get("ev") or 0.0)
        cm_id = int(row.get("canonical_match_id") or 0) or None

        # Check cooldown
        if is_alert_on_cooldown(db, cm_id, bookmaker_name, side, odds, ev, cooldown_hours):
            skipped += 1
            continue

        signal_data = {
            "canonical_match_id": cm_id,
            "match_label": match_label,
            "league": row.get("league"),
            "match_start_at": row.get("start_time_normalized"),
            "side": side,
            "team_name": team_name,
            "bookmaker_name": bookmaker_name,
            "odds": odds,
            "model_prob": row.get("model_prob"),
            "market_prob": row.get("market_prob"),
            "ev": ev,
            "suggested_stake": row.get("stake_suggestion"),
        }

        channel_names = []
        errors = []

        if force_dry_run or (not can_discord and not can_telegram):
            # Simulated mode
            status = "simulated" if (not can_discord and not can_telegram) else "sent"
            channel_names.append("simulation")
            dispatched += 1
        else:
            # Real send
            if can_discord and discord_url:
                embed = build_discord_embed(signal_data)
                ok, err = send_discord_notification(discord_url, embed)
                if ok:
                    channel_names.append("discord")
                else:
                    errors.append(f"Discord: {err}")

            if can_telegram and tg_token and tg_chat:
                html_msg = build_telegram_html(signal_data)
                ok, err = send_telegram_notification(tg_token, tg_chat, html_msg)
                if ok:
                    channel_names.append("telegram")
                else:
                    errors.append(f"Telegram: {err}")

            if channel_names:
                status = "sent"
                dispatched += 1
            else:
                status = "failed"
                failed += 1

        # Audit log entry
        log_entry = ValueAlertLog(
            created_at=datetime.now(timezone.utc).isoformat(),
            canonical_match_id=cm_id,
            match_label=match_label,
            league=row.get("league"),
            match_start_at=row.get("start_time_normalized"),
            side=side,
            team_name=team_name,
            bookmaker_name=bookmaker_name,
            odds=odds,
            model_prob=row.get("model_prob"),
            market_prob=row.get("market_prob"),
            ev=ev,
            suggested_stake=row.get("stake_suggestion"),
            channels=",".join(channel_names) if channel_names else "none",
            status=status,
            message_payload=json.dumps(signal_data),
            error_message="; ".join(errors) if errors else None,
        )
        db.add(log_entry)
        alert_results.append({
            "match": match_label,
            "team": team_name,
            "bookmaker": bookmaker_name,
            "odds": odds,
            "ev": ev,
            "channels": channel_names,
            "status": status,
        })

    db.commit()
    return {
        "dispatched": dispatched,
        "skipped": skipped,
        "failed": failed,
        "alerts": alert_results,
        "message": f"Przeskanowano sygnały: wysłano {dispatched}, pominięto (cooldown) {skipped}, błędów {failed}.",
    }


def send_test_alert(db: Session, channel: str = "both") -> Dict[str, Any]:
    """Send a test Value Bet notification to verify webhook/bot connectivity."""
    cfg = get_or_create_alert_config(db)

    test_signal = {
        "match_label": "Bilibili Gaming vs Anyone's Legend",
        "league": "LPL 2026 Split 3",
        "side": "b",
        "team_name": "Anyone's Legend",
        "bookmaker_name": "Superbet",
        "odds": 2.45,
        "model_prob": 0.485,
        "market_prob": 0.390,
        "ev": 0.076,  # +7.6% EV
        "suggested_stake": 2.5,
        "match_start_at": (datetime.now(timezone.utc) + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M UTC"),
    }

    results = {}
    discord_url = cfg.discord_webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    tg_token = cfg.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = cfg.telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if channel in {"both", "discord"}:
        if discord_url:
            embed = build_discord_embed(test_signal)
            embed["title"] = "🧪 [TEST] " + embed["title"]
            ok, err = send_discord_notification(discord_url, embed)
            results["discord"] = {"ok": ok, "error": err}
        else:
            results["discord"] = {"ok": False, "error": "Brak skonfigurowanego URL Discord Webhook"}

    if channel in {"both", "telegram"}:
        if tg_token and tg_chat:
            html_msg = "🧪 <b>[POWIADOMIENIE TESTOWE]</b>\n\n" + build_telegram_html(test_signal)
            ok, err = send_telegram_notification(tg_token, tg_chat, html_msg)
            results["telegram"] = {"ok": ok, "error": err}
        else:
            results["telegram"] = {"ok": False, "error": "Brak skonfigurowanego tokenu lub Chat ID Telegrama"}

    # Log the test
    log_entry = ValueAlertLog(
        created_at=datetime.now(timezone.utc).isoformat(),
        match_label="[TEST] Bilibili Gaming vs Anyone's Legend",
        league="LPL 2026 Split 3",
        side="b",
        team_name="Anyone's Legend",
        bookmaker_name="Superbet",
        odds=2.45,
        model_prob=0.485,
        market_prob=0.390,
        ev=0.076,
        suggested_stake=2.5,
        channels=channel,
        status="test",
        message_payload=json.dumps(test_signal),
        error_message=str(results),
    )
    db.add(log_entry)
    db.commit()

    return results
