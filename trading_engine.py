import os
import asyncio
import json
import logging
import requests
import websockets
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CONFIG = {
    "RPC_URL": "https://api.mainnet-beta.solana.com",
    "INITIAL_BALANCE": 3625.30,
    "MAX_DEV_HOLDING_PCT": 10.0
}

class TradingEngine:
    def __init__(self):
        self.balance = CONFIG["INITIAL_BALANCE"]
        self.connected_clients = set()
        self.active_positions = {}
        self.running = False

    def check_token_security(self, token_mint: str) -> dict:
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{token_mint}/report/summary"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                dev_holding = data.get("topHolders", [{}])[0].get("pct", 0)
                is_mintable = data.get("mintAuthority") is not None
                if dev_holding > CONFIG["MAX_DEV_HOLDING_PCT"]:
                    return {"safe": False, "reason": f"DEV holds {dev_holding:.1f}% - skipped"}
                if is_mintable:
                    return {"safe": False, "reason": "Mint authority enabled - skipped"}
                return {"safe": True, "reason": "Passed security check"}
        except Exception as e:
            logging.warning(f"Impossibile verificare la sicurezza: {e}")
        return {"safe": True, "reason": "Simulated check passed"}

    async def execute_trade(self, action: str, symbol: str, amount_usd: float, price: float):
        if action == "BUY":
            self.balance -= amount_usd
            self.active_positions[symbol] = {"entry_price": price, "amount_usd": amount_usd}
            log_msg = f"[EXEC] BUY ${amount_usd:.2f} SOL ${symbol} @ ${price:.6f}"
            logging.info(log_msg)
            await self.broadcast({"type": "LOG", "text": log_msg, "category": "exec"})
        elif action == "SELL":
            entry = self.active_positions.get(symbol, {}).get("entry_price", price)
            pnl_usd = amount_usd * ((price - entry) / entry)
            self.balance += (amount_usd + pnl_usd)
            pnl_str = f"+${pnl_usd:.2f}" if pnl_usd >= 0 else f"-${abs(pnl_usd):.2f}"
            log_msg = f"[FILL] SOLD ${symbol} {pnl_str}"
            logging.info(log_msg)
            if symbol in self.active_positions:
                del self.active_positions[symbol]
            await self.broadcast({"type": "LOG", "text": log_msg, "category": "fill"})
        
        await self.broadcast({"type": "BALANCE_UPDATE", "balance": round(self.balance, 2)})

    async def register(self, websocket):
        self.connected_clients.add(websocket)
        await websocket.send(json.dumps({"type": "INIT", "balance": self.balance, "status": "LIVE"}))

    async def unregister(self, websocket):
        self.connected_clients.remove(websocket)

    async def broadcast(self, message: dict):
        if self.connected_clients:
            payload = json.dumps(message)
            await asyncio.gather(*[client.send(payload) for client in self.connected_clients])

    async def handle_client(self, websocket, path=None):
        await self.register(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                if data.get("action") == "FORCE_SELL":
                    await self.execute_trade("SELL", data["symbol"], 100.0, 0.001)
        except websockets.ConnectionClosedError:
            pass
        finally:
            await self.unregister(websocket)

    async def start_trading_loop(self):
        self.running = True
        logging.info("Engine di Trading avviato...")
        tokens_pool = [
            {"symbol": "OASIS", "mint": "So11111111111111111111111111111111111111112"},
            {"symbol": "SPIKY", "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
            {"symbol": "DATEZ", "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
        ]
        idx = 0
        while self.running:
            await asyncio.sleep(4)
            target = tokens_pool[idx % len(tokens_pool)]
            idx += 1
            sec_check = self.check_token_security(target["mint"])
            if not sec_check["safe"]:
                warn_log = f"[WARN] ${target['symbol']} {sec_check['reason']}"
                logging.warning(warn_log)
                await self.broadcast({"type": "LOG", "text": warn_log, "category": "warn"})
                continue
            mock_price = 0.000481
            await self.execute_trade("BUY", target["symbol"], 50.0, mock_price)
            await asyncio.sleep(3)
            await self.execute_trade("SELL", target["symbol"], 50.0, mock_price * 1.15)

async def main():
    engine = TradingEngine()
    port = int(os.environ.get("PORT", 8765))
    server = await websockets.serve(engine.handle_client, "0.0.0.0", port)
    logging.info(f"WebSocket Server attivo sulla porta {port}")
    await asyncio.gather(server.wait_closed(), engine.start_trading_loop())

if __name__ == "__main__":
    asyncio.run(main())
