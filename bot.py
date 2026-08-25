import asyncio
import json
import logging
import os
from pathlib import Path
import time

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


def get_rug_analysis(address, coin):
    try:
        response = requests.get(
            f"https://api.rugcheck.xyz/v1/tokens/{address}/report",
            timeout=20,
        )
        response.raise_for_status()
        report = response.json()
    except requests.RequestException as error:
        logging.warning("Rug analysis unavailable for %s: %s", address, error)
        return {
            "rating": None,
            "details": "⚪ Rug analysis was unavailable when this alert fired.",
            "color": 0xF4C152,
        }

    token = report.get("token") or {}
    metadata = report.get("tokenMeta") or {}
    risks = report.get("risks") or []
    risk_names = " ".join(str(risk.get("name", "")).lower() for risk in risks)
    score = 0.0
    details = []

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

    if metadata.get("mutable") or metadata.get("updateAuthority"):
        score += 0.5
        details.append("🟡 Ownership: metadata/admin authority remains")
    else:
        details.append("🟢 Ownership: metadata control revoked")

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

    top_ten = number_value(coin, "top10HoldersPercent", "top_10_holders_percent")
    developer = number_value(coin, "developerHoldingPercent", "developer_holding_percent")
    insiders = number_value(coin, "insiderPercentage", "insider_percentage")
    concentration_parts = []
    if top_ten is not None:
        concentration_parts.append(f"top 10 {top_ten:.1f}%")
        score += 2.0 if top_ten >= 50 else 1.0 if top_ten >= 30 else 0.5 if top_ten >= 20 else 0
    if developer is not None:
        concentration_parts.append(f"developer {developer:.1f}%")
        score += 1.5 if developer >= 10 else 0.75 if developer >= 5 else 0
    if insiders is not None:
        concentration_parts.append(f"insiders {insiders:.1f}%")
        score += 1.0 if insiders >= 20 else 0.5 if insiders >= 10 else 0
    if concentration_parts:
        high_concentration = (top_ten or 0) >= 30 or (developer or 0) >= 5 or (insiders or 0) >= 10
        icon = "🔴" if high_concentration else "🟢"
        details.append(f"{icon} Wallets: {', '.join(concentration_parts)}")
    elif report.get("graphInsidersDetected"):
        score += 1.0
        details.append("🔴 Wallets: connected insider network detected")
    else:
        details.append("⚪ Wallets: concentration data not reported")

    bundled = number_value(coin, "bundlePercentage", "bundle_percentage")
    insider_graph = bool(report.get("graphInsidersDetected"))
    if bundled is not None:
        score += 2.0 if bundled >= 20 else 1.0 if bundled >= 10 else 0.5 if bundled >= 5 else 0
        icon = "🔴" if bundled >= 10 else "🟡" if bundled >= 5 else "🟢"
        graph_note = " + insider links" if insider_graph else ""
        details.append(f"{icon} Bundling: {bundled:.1f}%{graph_note}")
    elif insider_graph:
        score += 1.0
        details.append("🔴 Bundling: linked insider wallets detected")
    else:
        details.append("⚪ Bundling: Axiom did not report bundle data")

    normalized = number_value(report, "score_normalised")
    if normalized is not None:
        score = max(score, normalized / 10)

    rating = round(min(10, score), 1)
    important_risks = [risk for risk in risks if risk.get("description")][:2]
    for risk in important_risks:
        details.append(f"• {risk['description']}")

    color = 0xFF6B73 if rating >= 7 else 0xF4C152 if rating >= 4 else 0x62E6A7
    return {"rating": rating, "details": "\n".join(details)[:1024], "color": color}


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


async def run_bot():
    env_file = os.getenv("AXIOM_ENV_FILE", APP_DIR / ".env")
    load_dotenv(env_file)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
    access_token = os.environ["AXIOM_ACCESS_TOKEN"]
    refresh_token = os.environ["AXIOM_REFRESH_TOKEN"]
    start_market_cap = float(os.getenv("START_MARKET_CAP", "5000"))
    target_market_cap = float(os.getenv("TARGET_MARKET_CAP", "20000"))
    move_window_seconds = float(os.getenv("MOVE_WINDOW_SECONDS", "40"))

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

        if not price_feed_ready:
            price_feed_ready = True
            logging.info("Live Axiom market-cap updates are flowing")

        now = time.monotonic()
        move = moves.get(address)

        if market_cap < start_market_cap:
            moves.pop(address, None)
            return

        if move is None:
            if market_cap >= target_market_cap:
                return
            moves[address] = {"started_at": now, "started_cap": market_cap}
            ticker = first_value(coin, "tokenTicker", "token_ticker") or address[:8]
            logging.info(
                "Tracking %s from $%.0f toward $%.0f",
                ticker,
                market_cap,
                target_market_cap,
            )
            return

        elapsed = now - move["started_at"]
        if market_cap < target_market_cap or elapsed > move_window_seconds:
            return

        rug = await asyncio.to_thread(get_rug_analysis, address, coin)
        await asyncio.to_thread(
            send_discord_alert,
            webhook_url,
            coin,
            start_market_cap,
            target_market_cap,
            market_cap,
            elapsed,
            rug,
        )
        alerted_coins.add(address)
        moves.pop(address, None)
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
                if not pair_address or not address or pair_address in coins_by_pair:
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
                "Watching Axiom for $%.0f to $%.0f moves within %.0f seconds",
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_bot())
