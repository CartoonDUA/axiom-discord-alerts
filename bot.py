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


def send_discord_alert(
    webhook_url, coin, start_market_cap, target_market_cap, market_cap, elapsed
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
                "color": 0x62E6A7,
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
                ],
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

        await asyncio.to_thread(
            send_discord_alert,
            webhook_url,
            coin,
            start_market_cap,
            target_market_cap,
            market_cap,
            elapsed,
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
