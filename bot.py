import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time

import discord
from discord import app_commands
import requests
from axiomtradeapi import AxiomTradeClient
from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("AXIOM_DATA_DIR", APP_DIR))
STATE_FILE = DATA_DIR / "alerted_coins.json"
sol_price = None
sol_price_checked_at = 0


def first_value(coin, *keys):
    for key in keys:
        value = coin.get(key)
        if value not in (None, ""):
            return value
    return None


def get_sol_price():
    global sol_price, sol_price_checked_at

    if sol_price and time.time() - sol_price_checked_at < 60:
        return sol_price

    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "solana", "vs_currencies": "usd"},
        timeout=15,
    )
    response.raise_for_status()
    sol_price = float(response.json()["solana"]["usd"])
    sol_price_checked_at = time.time()
    return sol_price


def load_alerted_coins():
    if not STATE_FILE.exists():
        return set()
    return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))


def save_alerted_coins(coins):
    STATE_FILE.write_text(json.dumps(sorted(coins), indent=2), encoding="utf-8")


def number_value(data, *keys):
    value = first_value(data, *keys)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentage_value(data, *keys):
    value = number_value(data, *keys)
    if value is not None and 0 <= value <= 1:
        return value * 100
    return value


def get_bubble_networks(address):
    try:
        response = requests.get(
            f"https://api.rugcheck.xyz/v1/tokens/{address}/insiders/networks",
            timeout=10,
        )
        response.raise_for_status()
        networks = response.json()
        return networks if isinstance(networks, list) else []
    except requests.RequestException as error:
        logging.warning("Bubble-map analysis unavailable for %s: %s", address, error)
        return None


def get_rug_analysis(address, coin):
    creator = first_value(coin, "creatorAddress", "creator_address", "creator")
    try:
        for attempt in range(3):
            response = requests.get(
                f"https://api.rugcheck.xyz/v1/tokens/{address}/report",
                timeout=20,
            )
            response.raise_for_status()
            report = response.json()
            report_ready = (
                bool(report.get("markets"))
                and report.get("totalMarketLiquidity") is not None
                and bool(report.get("topHolders"))
            )
            if report_ready or attempt == 2:
                break
            time.sleep(1)
    except requests.RequestException as error:
        logging.warning("Rug analysis unavailable for %s: %s", address, error)
        return {
            "rating": None,
            "details": "⚪ Rug analysis was unavailable when this alert fired.",
            "color": 0xF4C152,
            "name": first_value(coin, "tokenName", "token_name", "name") or "Unknown coin",
            "ticker": first_value(coin, "tokenTicker", "token_ticker", "ticker", "symbol") or "?",
            "deployer": (
                f"[{creator[:8]}…](https://solscan.io/account/{creator}) · history unavailable"
                if creator
                else "Creator wallet and history unavailable"
            ),
        }

    token = report.get("token") or {}
    metadata = report.get("tokenMeta") or {}
    risks = report.get("risks") or []
    bubble_networks = report.get("insiderNetworks")
    if bubble_networks is None:
        bubble_networks = get_bubble_networks(address)
    risk_names = " ".join(str(risk.get("name", "")).lower() for risk in risks)
    creator = report.get("creator") or creator
    creator_tokens = report.get("creatorTokens") or []
    creator_history_risk = next(
        (
            risk
            for risk in risks
            if "creator history" in str(risk.get("name", "")).lower()
            and "rug" in str(risk.get("name", "")).lower()
        ),
        None,
    )
    score = 0.0
    details = []

    if creator:
        prior_count = len(creator_tokens)
        if creator_history_risk:
            score += 3.0
            details.append(f"🔴 Deployer: {prior_count} prior launches; rugged-token history flagged")
        elif prior_count:
            if prior_count >= 10:
                score += 0.5
            details.append(f"🟡 Deployer: {prior_count} prior launches; no rugged history flagged")
        else:
            score += 0.5
            details.append("⚪ Deployer: fresh wallet; no history available to judge")
        deployer = (
            f"[{creator[:8]}…{creator[-4:]}](https://solscan.io/account/{creator}) · "
            f"{prior_count} prior launches"
            + (" · **RUGGED HISTORY FLAGGED**" if creator_history_risk else "")
        )
    else:
        details.append("⚪ Deployer: creator wallet not reported")
        deployer = "Creator wallet and history unavailable"

    mint_authority = report.get("mintAuthority") or token.get("mintAuthority")
    if mint_authority:
        score += 2.0
        details.append("🔴 Minting: authority is still active")
    else:
        details.append("🟢 Minting: authority revoked")

    freeze_authority = report.get("freezeAuthority") or token.get("freezeAuthority")
    transfer_fee = report.get("transferFee") or {}
    transfer_fee_value = (
        number_value(transfer_fee, "pct", "feeBps", "basisPoints", "transferFeeBasisPoints")
        if isinstance(transfer_fee, dict)
        else None
    )
    transfer_risk = (transfer_fee_value or 0) > 0 or any(
        word in risk_names for word in ("honeypot", "sell", "transfer fee", "transfer hook")
    )
    if freeze_authority or transfer_risk:
        score += 1.5
        reason = "freeze authority active" if freeze_authority else "transfer restrictions reported"
        details.append(f"🔴 Sell controls: {reason}")
    else:
        details.append("🟢 Sell controls: no freeze or transfer restriction reported")

    update_authority = metadata.get("updateAuthority")
    has_admin_control = metadata.get("mutable") and update_authority not in (
        None,
        "11111111111111111111111111111111",
    )
    if has_admin_control:
        score += 0.5
        details.append("🟡 Ownership: metadata/admin authority remains")
    else:
        details.append("🟢 Ownership: metadata control revoked")

    total_liquidity = number_value(report, "totalMarketLiquidity")
    low_liquidity_risk = any(
        "low liquidity" in str(risk.get("name", "")).lower() for risk in risks
    )
    if total_liquidity is not None:
        liquidity_score = (
            4.0
            if total_liquidity < 100
            else 3.0
            if total_liquidity < 1000
            else 2.0
            if total_liquidity < 5000
            else 1.0
            if total_liquidity < 10000
            else 0
        )
        if low_liquidity_risk:
            liquidity_score = max(liquidity_score, 5.5)
        score += liquidity_score
        icon = "🔴" if liquidity_score >= 3 else "🟡" if liquidity_score else "🟢"
        danger_note = " · danger-level warning" if low_liquidity_risk else ""
        details.append(f"{icon} Liquidity depth: ${total_liquidity:,.2f}{danger_note}")
    elif low_liquidity_risk:
        score += 5.5
        details.append("🔴 Liquidity depth: danger-level low-liquidity warning")

    locked_values = [
        number_value(market.get("lp") or {}, "lpLockedPct")
        for market in report.get("markets") or []
    ]
    locked_values = [value for value in locked_values if value is not None]
    locked_pct = max(locked_values) if locked_values else None
    if locked_pct is None:
        details.append("⚪ Liquidity: lock status not reported")
    elif locked_pct < 50:
        score += 2.0
        details.append(f"🔴 Liquidity: only {locked_pct:.1f}% locked/burned")
    elif locked_pct < 90:
        score += 1.0
        details.append(f"🟡 Liquidity: {locked_pct:.1f}% locked/burned")
    else:
        details.append(f"🟢 Liquidity: {locked_pct:.1f}% locked/burned")

    pool_accounts = {
        market.get("liquidityA")
        for market in report.get("markets") or []
        if market.get("liquidityA")
    }
    report_holders = [
        holder
        for holder in report.get("topHolders") or []
        if holder.get("address") not in pool_accounts
    ]
    report_top_wallet = max(
        (number_value(holder, "pct") or 0 for holder in report_holders),
        default=None,
    )
    report_top_ten = sum(
        number_value(holder, "pct") or 0 for holder in report_holders[:10]
    ) if report_holders else None
    top_ten = number_value(coin, "top10HoldersPercent", "top_10_holders_percent")
    if top_ten is None:
        top_ten = report_top_ten
    developer = number_value(coin, "developerHoldingPercent", "developer_holding_percent")
    insiders = number_value(coin, "insiderPercentage", "insider_percentage")
    concentration_parts = []
    if report_top_wallet is not None:
        concentration_parts.append(f"largest wallet {report_top_wallet:.1f}%")
        score += 2.0 if report_top_wallet >= 20 else 1.5 if report_top_wallet >= 10 else 0.5 if report_top_wallet >= 5 else 0
    if top_ten is not None:
        concentration_parts.append(f"top 10 {top_ten:.1f}%")
        score += 2.0 if top_ten >= 50 else 1.5 if top_ten >= 30 else 1.0 if top_ten >= 20 else 0
    if developer is not None:
        concentration_parts.append(f"developer {developer:.1f}%")
        score += 1.5 if developer >= 10 else 0.75 if developer >= 5 else 0
    if insiders is not None:
        concentration_parts.append(f"insiders {insiders:.1f}%")
        score += 1.0 if insiders >= 20 else 0.5 if insiders >= 10 else 0
    if concentration_parts:
        high_concentration = (report_top_wallet or 0) >= 10 or (top_ten or 0) >= 30 or (developer or 0) >= 5 or (insiders or 0) >= 10
        icon = "🔴" if high_concentration else "🟢"
        details.append(f"{icon} Wallets: {', '.join(concentration_parts)}")
    else:
        details.append("⚪ Wallets: concentration data not reported")

    bundled = number_value(coin, "bundlePercentage", "bundle_percentage")
    if bundled is not None:
        score += 2.0 if bundled >= 20 else 1.0 if bundled >= 10 else 0.5 if bundled >= 5 else 0
        icon = "🔴" if bundled >= 10 else "🟡" if bundled >= 5 else "🟢"
        details.append(f"{icon} Bundling: {bundled:.1f}%")
    else:
        details.append("⚪ Bundling: Axiom did not report bundle data")

    token_supply = number_value(token, "supply")
    if bubble_networks:
        bubble_rows = []
        for network in bubble_networks:
            amount = number_value(network, "totalAmount", "tokenAmount") or 0
            percentage = amount / token_supply * 100 if token_supply else 0
            wallets = int(number_value(network, "numActiveAccounts", "activeAccounts", "size") or 0)
            bubble_rows.append((percentage, wallets, network.get("activityType") or network.get("type") or "linked"))
        bubble_rows.sort(reverse=True)
        largest_pct, largest_wallets, link_type = bubble_rows[0]
        total_pct = min(100, sum(row[0] for row in bubble_rows))
        bubble_score = (
            7.0
            if largest_pct >= 50
            else 5.0
            if largest_pct >= 25
            else 3.5
            if largest_pct >= 15
            else 1.5
            if largest_pct >= 5
            else 0.5
        )
        if largest_wallets >= 10:
            bubble_score += 1.0
        score += bubble_score
        icon = "🔴" if bubble_score >= 3 else "🟡"
        details.append(
            f"{icon} Bubble map: {len(bubble_rows)} linked cluster{'s' if len(bubble_rows) != 1 else ''}; "
            f"largest {largest_wallets} wallets / {largest_pct:.1f}% supply via {link_type} "
            f"({total_pct:.1f}% across clusters)"
        )
    elif report.get("graphInsidersDetected"):
        score += 3.0
        details.append(f"🔴 Bubble map: {report['graphInsidersDetected']} connected insider wallets detected")
    elif bubble_networks == [] and report.get("graphInsidersDetected") is not None:
        details.append("🟢 Bubble map: no connected holder clusters detected")
    else:
        details.append("⚪ Bubble map: network data unavailable or not indexed yet")

    normalized = number_value(report, "score_normalised")
    if normalized is not None:
        score += min(2, normalized / 20)

    missing_data = []
    if not report.get("markets"):
        missing_data.append("market")
    if total_liquidity is None:
        missing_data.append("liquidity")
    if not report_holders and top_ten is None:
        missing_data.append("holder")
    if missing_data:
        uncertainty_floor = 7.0 if len(missing_data) >= 2 else 5.0
        score = max(score, uncertainty_floor)
        details.insert(
            0,
            f"🔴 Data confidence: {', '.join(missing_data)} data not indexed yet; risk cannot be verified",
        )
    if low_liquidity_risk:
        score = max(score, 7.0)

    rating = round(min(10, score), 1)
    important_risks = [
        risk
        for risk in risks
        if risk.get("description") and risk is not creator_history_risk
    ][:2]
    for risk in important_risks:
        details.append(f"• {risk['description']}")

    color = 0xFF6B73 if rating >= 7 else 0xF4C152 if rating >= 4 else 0x62E6A7
    return {
        "rating": rating,
        "details": "\n".join(details)[:1024],
        "color": color,
        "name": first_value(metadata, "name") or first_value(coin, "tokenName", "token_name", "name") or "Unknown coin",
        "ticker": first_value(metadata, "symbol") or first_value(coin, "tokenTicker", "token_ticker", "ticker", "symbol") or "?",
        "deployer": deployer,
    }


def create_discord_client(guild_id):
    client = discord.Client(intents=discord.Intents.none())
    commands = app_commands.CommandTree(client)
    synced = False

    @commands.command(name="check", description="Check a Solana coin for rug-risk signals")
    @app_commands.describe(ca="Solana coin address (CA)")
    async def check(interaction: discord.Interaction, ca: str):
        address = ca.strip()
        if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,50}", address):
            await interaction.response.send_message("That does not look like a valid Solana coin address.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        rug = await asyncio.to_thread(get_rug_analysis, address, {})
        rating = f"{rug['rating']}/10" if rug["rating"] is not None else "UNAVAILABLE"
        axiom_url = f"https://axiom.trade/t/{address}"
        embed = discord.Embed(
            title=f"{rug['name']} (${rug['ticker']}) rug-risk report",
            url=axiom_url,
            color=rug["color"],
            description=f"Automated on-chain screening for `{address}`.",
        )
        embed.add_field(name="Open in Axiom", value=f"[View coin]({axiom_url})", inline=False)
        embed.add_field(name="Coin address", value=f"```{address}```", inline=False)
        embed.add_field(name="Deployer trace", value=rug["deployer"], inline=False)
        embed.add_field(name=f"RUG RISK • {rating}", value=rug["details"], inline=False)
        embed.set_footer(text="Automated on-chain screening from RugCheck and Axiom data — not a guarantee.")
        await interaction.followup.send(embed=embed)

    @client.event
    async def on_ready():
        nonlocal synced
        if not synced:
            if guild_id:
                server = discord.Object(id=int(guild_id))
                commands.copy_global_to(guild=server)
                await commands.sync(guild=server)
            else:
                await commands.sync()
            synced = True
        logging.info("Discord /check command ready as %s", client.user)

    return client


async def run_discord_commands(token, guild_id):
    client = create_discord_client(guild_id)
    try:
        await client.start(token)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logging.error("Discord slash commands stopped: %s", error)
    finally:
        if not client.is_closed():
            await client.close()


def send_discord_alert(
    webhook_url, coin, start_market_cap, target_market_cap, market_cap, elapsed, rug
):
    address = first_value(coin, "tokenAddress", "token_address", "address", "mint")
    name = first_value(coin, "tokenName", "token_name", "name") or "Unknown coin"
    ticker = first_value(coin, "tokenTicker", "token_ticker", "ticker", "symbol") or "?"
    axiom_url = f"https://axiom.trade/t/{address}"

    payload = {
        "username": "Axiom Market Cap Alerts",
        "embeds": [
            {
                "title": f"{name} (${ticker}) hit ${target_market_cap:,.0f}",
                "url": axiom_url,
                "color": rug["color"],
                "description": (
                    f"Moved from **${start_market_cap:,.0f}** to "
                    f"**${market_cap:,.0f}** in **{elapsed:.1f} seconds**."
                ),
                "fields": [
                    {
                        "name": "Trigger",
                        "value": f"${start_market_cap:,.0f} → ${target_market_cap:,.0f}",
                        "inline": True,
                    },
                    {
                        "name": "Time",
                        "value": f"{elapsed:.1f}s",
                        "inline": True,
                    },
                    {
                        "name": "Open in Axiom",
                        "value": f"[View coin]({axiom_url})",
                        "inline": True,
                    },
                    {"name": "Coin address", "value": f"```{address}```"},
                    {"name": "Deployer trace", "value": rug["deployer"]},
                    {
                        "name": (
                            f"RUG RISK • {rug['rating']}/10"
                            if rug["rating"] is not None
                            else "RUG RISK • UNAVAILABLE"
                        ),
                        "value": rug["details"],
                    },
                ],
                "footer": {
                    "text": "Automated on-chain screening from RugCheck and Axiom data — not a guarantee."
                },
            }
        ],
    }

    response = requests.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()


def send_green_candle_alert(webhook_url, coin, gain_percent, original_call_url):
    address = first_value(coin, "tokenAddress", "token_address", "address", "mint")
    ticker = first_value(coin, "tokenTicker", "token_ticker", "ticker", "symbol") or "?"
    ticker = ticker.lstrip("$")
    percentage = f"{gain_percent:g}"
    axiom_url = f"https://axiom.trade/t/{address}"
    description = f"**Premium just caught ${ticker} hitting +{percentage}%** · 🟣 Solana"
    if original_call_url:
        description += (
            f"\n\n[See the original call that made this happen]({original_call_url})"
        )
    payload = {
        "username": "Premium Green Candle",
        "embeds": [
            {
                "title": f"+{percentage}% · ${ticker} · GREEN CANDLE",
                "url": axiom_url,
                "description": description,
                "color": 0x62E6A7,
            }
        ],
    }
    response = requests.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()


def send_momentum_alert(webhook_url, coin, gain_percent, elapsed, rug):
    address = first_value(coin, "tokenAddress", "token_address", "address", "mint")
    ticker = (first_value(coin, "tokenTicker", "token_ticker", "ticker", "symbol") or "?").lstrip("$")
    percentage = f"{gain_percent:g}"
    axiom_url = f"https://axiom.trade/t/{address}"
    rating = f"{rug['rating']}/10" if rug["rating"] is not None else "UNAVAILABLE"
    payload = {
        "username": "Premium Momentum",
        "embeds": [
            {
                "title": f"+{percentage}% · ${ticker} · RISING FAST",
                "url": axiom_url,
                "description": f"**Premium caught ${ticker} starting to move** · +{percentage}% in {elapsed:.1f}s · 🟣 Solana",
                "color": rug["color"],
                "fields": [
                    {
                        "name": "Open in Axiom",
                        "value": f"[View coin]({axiom_url})",
                        "inline": True,
                    },
                    {
                        "name": "Coin address",
                        "value": f"```{address}```",
                        "inline": False,
                    },
                    {
                        "name": "Deployer trace",
                        "value": rug["deployer"],
                        "inline": False,
                    },
                    {"name": "Why this score", "value": rug["details"], "inline": False},
                ],
                "footer": {
                    "text": f"RUG RISK • {rating} · Automated screening — not a guarantee."
                },
            }
        ],
    }
    response = requests.post(
        webhook_url,
        params={"wait": "true"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    message = response.json()
    if message.get("guild_id") and message.get("channel_id") and message.get("id"):
        return (
            f"https://discord.com/channels/{message['guild_id']}/"
            f"{message['channel_id']}/{message['id']}"
        )
    return None


def choose_webhook(rating, routes):
    if rating is None:
        return None
    for minimum, webhook_url in sorted(routes, reverse=True):
        if webhook_url and rating >= minimum:
            return webhook_url
    return None


def passes_audit(coin, market_cap, settings):
    created_at = first_value(coin, "created_at", "createdAt", "pairCreatedAt", "open_trading")
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - created).total_seconds() / 60
    extra = coin.get("extra") if isinstance(coin.get("extra"), dict) else {}
    pro_traders = number_value(coin, "pro_traders", "proTraders", "pro_trader_count", "proTraderCount")
    if pro_traders is None:
        pro_traders = number_value(extra, "pro_traders", "proTraders", "pro_trader_count", "proTraderCount") or 0
    global_fees = number_value(coin, "global_fees_paid", "globalFeesPaid", "global_fees_paid_sol", "globalFeesPaidSol")
    if global_fees is None:
        global_fees = number_value(extra, "global_fees_paid", "globalFeesPaid", "global_fees_paid_sol", "globalFeesPaidSol") or 0
    twitter = first_value(coin, "twitter", "twitterUrl", "twitter_url")
    top_ten = percentage_value(
        coin,
        "top_10_holders",
        "top10HoldersPercent",
        "top_10_holders_percent",
    )
    developer = percentage_value(
        coin,
        "dev_holds_percent",
        "developerHoldingPercent",
        "developer_holding_percent",
    )
    snipers = percentage_value(
        coin,
        "snipers_hold_percent",
        "sniperPercentage",
        "sniper_percentage",
    )
    concentration_ok = (
        (settings["max_top_ten"] <= 0 or (top_ten is not None and top_ten <= settings["max_top_ten"]))
        and (settings["max_developer"] <= 0 or (developer is not None and developer <= settings["max_developer"]))
        and (settings["max_snipers"] <= 0 or (snipers is not None and snipers <= settings["max_snipers"]))
    )
    authorities_ok = (
        not settings["require_revoked_authorities"]
        or (
            not first_value(coin, "mint_authority", "mintAuthority")
            and not first_value(coin, "freeze_authority", "freezeAuthority")
        )
    )
    return (
        age_minutes <= settings["max_age"]
        and pro_traders >= settings["min_pro_traders"]
        and market_cap >= settings["min_market_cap"]
        and global_fees >= settings["min_global_fees"]
        and (not settings["require_twitter"] or bool(twitter))
        and concentration_ok
        and authorities_ok
    )


def log_tracking(action, coin, address, market_cap, target_market_cap, elapsed=0):
    logging.info(
        "TRACKING_EVENT %s",
        json.dumps(
            {
                "action": action,
                "address": address,
                "name": first_value(coin, "tokenName", "token_name", "name") or "Unknown coin",
                "ticker": first_value(coin, "tokenTicker", "token_ticker", "ticker", "symbol") or "?",
                "marketCap": round(market_cap),
                "targetCap": round(target_market_cap),
                "elapsed": round(elapsed, 1),
            },
            separators=(",", ":"),
        ),
    )


async def run_bot():
    env_file = os.getenv("AXIOM_ENV_FILE", APP_DIR / ".env")
    load_dotenv(env_file)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    all_webhook_url = os.getenv("DISCORD_ALL_WEBHOOK_URL", "").strip()
    green_candle_webhook_url = os.getenv("DISCORD_GREEN_CANDLE_WEBHOOK_URL", "").strip()
    green_candle_percent = float(os.getenv("GREEN_CANDLE_PERCENT", "100"))
    early_momentum_percent = float(os.getenv("EARLY_MOMENTUM_PERCENT", "10"))
    early_momentum_window = float(os.getenv("EARLY_MOMENTUM_WINDOW_SECONDS", "15"))
    early_momentum_hold = float(os.getenv("EARLY_MOMENTUM_HOLD_SECONDS", "2"))
    secondary_webhook_url = os.getenv("DISCORD_SECONDARY_WEBHOOK_URL", "").strip()
    webhook_routes = [
        (float(os.getenv("DISCORD_WEBHOOK_MIN_RATING", "4")), webhook_url),
        (float(os.getenv("DISCORD_SECONDARY_MIN_RATING", "2")), secondary_webhook_url),
    ]
    access_token = os.environ["AXIOM_ACCESS_TOKEN"]
    refresh_token = os.environ["AXIOM_REFRESH_TOKEN"]
    start_market_cap = float(os.getenv("START_MARKET_CAP", "5000"))
    target_market_cap = float(os.getenv("TARGET_MARKET_CAP", "20000"))
    max_tracking_entry_cap = float(os.getenv("MAX_TRACKING_ENTRY_CAP", "7500"))
    move_window_seconds = float(os.getenv("MOVE_WINDOW_SECONDS", "40"))
    audit_settings = {
        "max_age": float(os.getenv("AUDIT_MAX_AGE_MINUTES", "15")),
        "min_pro_traders": float(os.getenv("AUDIT_MIN_PRO_TRADERS", "0")),
        "min_market_cap": float(os.getenv("AUDIT_MIN_MARKET_CAP", "5000")),
        "min_global_fees": float(os.getenv("AUDIT_MIN_GLOBAL_FEES_SOL", "0")),
        "require_twitter": os.getenv("AUDIT_REQUIRE_TWITTER", "true").lower() == "true",
        "max_top_ten": float(os.getenv("AUDIT_MAX_TOP_10_PERCENT", "20")),
        "max_developer": float(os.getenv("AUDIT_MAX_DEV_HOLDING_PERCENT", "10")),
        "max_snipers": float(os.getenv("AUDIT_MAX_SNIPER_PERCENT", "10")),
        "require_revoked_authorities": os.getenv(
            "AUDIT_REQUIRE_REVOKED_AUTHORITIES", "true"
        ).lower()
        == "true",
    }

    alerted_coins = load_alerted_coins()
    coins_by_pair = {}
    moves = {}
    price_feed_ready = False
    client = AxiomTradeClient(
        auth_token=access_token,
        refresh_token=refresh_token,
        use_saved_tokens=False,
    )

    async def check_price(pair_address, price_sol):
        nonlocal price_feed_ready

        coin = coins_by_pair.get(pair_address)
        if not coin or sol_price is None:
            return

        address = first_value(coin, "tokenAddress", "token_address", "address", "mint")
        if not address or address in alerted_coins:
            return

        try:
            market_cap = float(price_sol) * float(coin["supply"]) * sol_price
        except (KeyError, TypeError, ValueError):
            return

        if not passes_audit(coin, market_cap, audit_settings):
            if address in moves:
                log_tracking("remove", coin, address, market_cap, target_market_cap)
            moves.pop(address, None)
            return

        if not price_feed_ready:
            price_feed_ready = True
            logging.info("Live Axiom market-cap updates are flowing")

        now = time.monotonic()
        move = moves.get(address)

        if market_cap < start_market_cap:
            if address in moves:
                log_tracking("remove", coin, address, market_cap, target_market_cap)
            moves.pop(address, None)
            return

        if move is None:
            if market_cap > max_tracking_entry_cap:
                return
            moves[address] = {
                "started_at": now,
                "started_cap": market_cap,
                "momentum_sent": False,
                "green_candle_sent": False,
                "last_update": now,
                "momentum_since": None,
                "momentum_message_url": None,
                "rug_task": asyncio.create_task(
                    asyncio.to_thread(get_rug_analysis, address, coin)
                ),
            }
            ticker = first_value(coin, "tokenTicker", "token_ticker") or address[:8]
            logging.info(
                "Tracking %s from $%.0f toward $%.0f",
                ticker,
                market_cap,
                target_market_cap,
            )
            log_tracking("start", coin, address, market_cap, target_market_cap)
            return

        elapsed = now - move["started_at"]
        if elapsed > move_window_seconds:
            moves.pop(address, None)
            log_tracking("remove", coin, address, market_cap, target_market_cap, elapsed)
            return

        if now - move["last_update"] >= 1:
            move["last_update"] = now
            log_tracking("update", coin, address, market_cap, target_market_cap, elapsed)

        green_candle_target = move["started_cap"] * (1 + green_candle_percent / 100)
        momentum_target = move["started_cap"] * (1 + early_momentum_percent / 100)
        if market_cap >= momentum_target:
            if move["momentum_since"] is None:
                move["momentum_since"] = now
        else:
            move["momentum_since"] = None
        if (
            green_candle_webhook_url
            and not move["momentum_sent"]
            and elapsed <= early_momentum_window
            and market_cap >= momentum_target
            and move["momentum_since"] is not None
            and now - move["momentum_since"] >= early_momentum_hold
        ):
            rug = await move["rug_task"]
            move["momentum_message_url"] = await asyncio.to_thread(
                send_momentum_alert,
                green_candle_webhook_url,
                coin,
                early_momentum_percent,
                elapsed,
                rug,
            )
            move["momentum_sent"] = True
            logging.info("Momentum alerted %s at +%g%% in %.1fs", address, early_momentum_percent, elapsed)

        if (
            green_candle_webhook_url
            and not move["green_candle_sent"]
            and market_cap >= green_candle_target
        ):
            actual_gain = (market_cap / move["started_cap"] - 1) * 100
            await asyncio.to_thread(
                send_green_candle_alert,
                green_candle_webhook_url,
                coin,
                round(actual_gain),
                move["momentum_message_url"],
            )
            move["green_candle_sent"] = True
            logging.info("Green Candle alerted %s at +%.0f%%", address, actual_gain)

        if market_cap < target_market_cap:
            return

        rug = await asyncio.to_thread(get_rug_analysis, address, coin)
        alert_webhooks = []
        if all_webhook_url:
            alert_webhooks.append(all_webhook_url)
        risk_webhook = choose_webhook(rug["rating"], webhook_routes)
        if risk_webhook and risk_webhook not in alert_webhooks:
            alert_webhooks.append(risk_webhook)
        for alert_webhook in alert_webhooks:
            await asyncio.to_thread(
                send_discord_alert,
                alert_webhook,
                coin,
                start_market_cap,
                target_market_cap,
                market_cap,
                elapsed,
                rug,
            )
        if not alert_webhooks:
            logging.info("No webhook route matched rug rating %s for %s", rug["rating"], address)
        alerted_coins.add(address)
        moves.pop(address, None)
        log_tracking("remove", coin, address, market_cap, target_market_cap, elapsed)
        save_alerted_coins(alerted_coins)
        logging.info(
            "ALERT_EVENT %s",
            json.dumps(
                {
                    "address": address,
                    "name": first_value(coin, "tokenName", "token_name", "name")
                    or "Unknown coin",
                    "ticker": first_value(
                        coin, "tokenTicker", "token_ticker", "ticker", "symbol"
                    )
                    or "?",
                    "marketCap": round(market_cap),
                    "elapsed": round(elapsed, 1),
                    "rugRating": rug["rating"],
                },
                separators=(",", ":"),
            ),
        )
        logging.info(
            "Alerted %s: $%.0f to $%.0f in %.1f seconds",
            address,
            move["started_cap"],
            market_cap,
            elapsed,
        )

    async def refresh_sol_price():
        while True:
            try:
                await asyncio.to_thread(get_sol_price)
            except Exception as error:
                logging.warning("Could not refresh SOL price: %s", error)
            await asyncio.sleep(30)

    await asyncio.to_thread(get_sol_price)

    while True:
        new_pairs = client.get_websocket_client()
        prices = client.get_websocket_client()

        async def price_message(raw):
            try:
                message = json.loads(raw)
                room = message.get("room", "")
                if room.startswith("b-") and message.get("content") is not None:
                    await check_price(room[2:], message["content"])
            except json.JSONDecodeError:
                return

        prices._dispatch = price_message

        async def subscribe_coin(coins):
            for coin in coins:
                pair_address = first_value(coin, "pairAddress", "pair_address")
                address = first_value(coin, "tokenAddress", "token_address")
                if not pair_address or not address:
                    continue

                if pair_address in coins_by_pair:
                    coins_by_pair[pair_address].update(coin)
                    continue

                coins_by_pair[pair_address] = coin
                await prices._send(
                    json.dumps({"action": "join", "room": f"b-{pair_address}"})
                )

        tasks = []
        try:
            if not await prices.connect():
                raise ConnectionError("Axiom price WebSocket connection failed")

            for pair_address in coins_by_pair:
                await prices._send(
                    json.dumps({"action": "join", "room": f"b-{pair_address}"})
                )

            if not await new_pairs.subscribe_new_tokens(subscribe_coin):
                raise ConnectionError("Axiom new-pairs subscription failed")

            logging.info(
                "Watching Axiom audit-passing coins for $%.0f to $%.0f moves within %.0f seconds",
                start_market_cap,
                target_market_cap,
                move_window_seconds,
            )
            tasks = [
                asyncio.create_task(prices.start()),
                asyncio.create_task(new_pairs.start()),
                asyncio.create_task(refresh_sol_price()),
            ]
            await asyncio.wait(tasks[:2], return_when=asyncio.FIRST_COMPLETED)
            raise ConnectionError("Axiom WebSocket connection closed")
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Connection lost; reconnecting in 5 seconds")
            await asyncio.sleep(5)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await prices.close()
            await new_pairs.close()


async def main():
    env_file = os.getenv("AXIOM_ENV_FILE", APP_DIR / ".env")
    load_dotenv(env_file)
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    if token:
        await asyncio.gather(run_bot(), run_discord_commands(token, guild_id))
    else:
        logging.info("Discord /check is disabled until a bot token is added in Settings")
        await run_bot()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
