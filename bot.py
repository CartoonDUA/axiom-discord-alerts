import asyncio
import json
import logging
import os
from pathlib import Path
import time

import requests
from axiomtradeapi import AxiomTradeClient
from dotenv import load_dotenv


MIN_MARKET_CAP = 5_000
MAX_MARKET_CAP = 20_000
STATE_FILE = Path(__file__).resolve().parent / "alerted_coins.json"
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


def market_cap_usd(coin, current_sol_price=None):
    is_sol = False
    value = first_value(
        coin,
        "marketCapUsd",
        "market_cap_usd",
        "marketCapUSD",
        "usdMarketCap",
    )
    if value is None:
        value = first_value(coin, "marketCapSol", "market_cap_sol")
        if value is None or current_sol_price is None:
            return None
        is_sol = True

    try:
        cap = float(str(value).replace("$", "").replace(",", ""))
        return cap * current_sol_price if is_sol else cap
    except ValueError:
        return None


def load_alerted_coins():
    if not STATE_FILE.exists():
        return set()
    return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))


def save_alerted_coins(coins):
    STATE_FILE.write_text(json.dumps(sorted(coins), indent=2), encoding="utf-8")


def send_discord_alert(webhook_url, coin, market_cap):
    address = first_value(coin, "tokenAddress", "token_address", "address", "mint")
    name = first_value(coin, "tokenName", "name") or "Unknown coin"
    ticker = first_value(coin, "tokenTicker", "ticker", "symbol") or "?"
    axiom_url = f"https://axiom.trade/t/{address}"

    payload = {
        "username": "Axiom Market Cap Alerts",
        "embeds": [
            {
                "title": f"{name} (${ticker}) crossed $5K",
                "url": axiom_url,
                "color": 0x22C55E,
                "fields": [
                    {
                        "name": "Market cap",
                        "value": f"${market_cap:,.0f}",
                        "inline": True,
                    },
                    {
                        "name": "Range",
                        "value": "$5K - $20K",
                        "inline": True,
                    },
                    {"name": "Token address", "value": f"`{address}`"},
                ],
            }
        ],
    }

    response = requests.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()


async def run_bot():
    load_dotenv()
    webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
    access_token = os.environ["AXIOM_ACCESS_TOKEN"]
    refresh_token = os.environ["AXIOM_REFRESH_TOKEN"]
    alerted_coins = load_alerted_coins()
    client = AxiomTradeClient(
        auth_token=access_token,
        refresh_token=refresh_token,
        use_saved_tokens=False,
    )

    async def check_coins(coins):
        for coin in coins:
            address = first_value(
                coin, "tokenAddress", "token_address", "address", "mint"
            )
            cap = market_cap_usd(coin)
            if cap is None and first_value(coin, "marketCapSol", "market_cap_sol"):
                current_sol_price = await asyncio.to_thread(get_sol_price)
                cap = market_cap_usd(coin, current_sol_price)

            if not address or cap is None:
                continue
            if address in alerted_coins or not MIN_MARKET_CAP <= cap <= MAX_MARKET_CAP:
                continue

            await asyncio.to_thread(send_discord_alert, webhook_url, coin, cap)
            alerted_coins.add(address)
            save_alerted_coins(alerted_coins)
            logging.info("Alerted %s at $%.0f", address, cap)

    while True:
        try:
            websocket = client.get_websocket_client()
            subscribed = await websocket.subscribe_new_tokens(check_coins)
            if not subscribed:
                raise ConnectionError("Axiom WebSocket subscription failed")

            logging.info("Watching Axiom for coins between $5K and $20K")
            await websocket.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Connection lost; reconnecting in 5 seconds")
            await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_bot())
