import asyncio
import json
import os
import http
import websockets
import requests
import base64
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
import base58

SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

bot_keypair = None
if SOLANA_PRIVATE_KEY:
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))
            bot_keypair = Keypair.from_bytes(key_bytes)
        else:
            bot_keypair = Keypair.from_bytes(base58.b58decode(SOLANA_PRIVATE_KEY))
        print(f"[SYSTEM] Wallet caricato con successo.")
    except Exception as e:
        print(f"[ERROR] Errore chiave privata: {e}")

connected_clients = set()

async def health_check(path, request_headers):
    if "Upgrade" not in request_headers.get("connection", "").lower() and \
       "websocket" not in request_headers.get("upgrade", "").lower():
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"Grok Bot Backend is Alive!"

async def execute_real_solana_buy():
    if not bot_keypair:
        return "[ERROR] Chiave privata mancante su Render!"

    try:
        user_pubkey = str(bot_keypair.pubkey())
        input_mint = "So11111111111111111111111111111111111111112"
        output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC
        amount_lamports = 10000000 # 0.01 SOL

        # Chiamata a Jupiter DEX API
        quote_res = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=100").json()
        if "error" in quote_res:
            return f"[ERROR] Jupiter Quote: {quote_res.get('error')}"

        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote_res,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True
        }).json()

        swap_tx_b64 = swap_res.get("swapTransaction")
        if not swap_tx_b64:
            return "[ERROR] Impossibile generare la transazione di swap."

        # Firma e invio
        raw_tx = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(raw_tx)
        signature = bot_keypair.sign_message(tx.message.to_bytes())
        signed_tx = VersionedTransaction.populate(tx.message, [signature])

        # Invio via RPC HTTP standard
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(bytes(signed_tx)).decode('utf-8'), {"encoding": "base64"}]
        }
        res = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload).json()
        
        if "result" in res:
            return f"[SUCCESS] ACQUISTO REALE COMPLETATO! Tx: {res['result']}"
        else:
            return f"[ERROR] Rifiutato dalla rete: {res.get('error', 'Unknown')}"

    except Exception as e:
        return f"[ERROR] Eccezione transazione: {str(e)}"

async def handle_messages(websocket, path):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("action") == "FORCE_BUY":
                await websocket.send(json.dumps({"type": "LOG", "text": "[EXEC] Invio ordine a Jupiter DEX...", "category": "exec"}))
                result = await execute_real_solana_buy()
                category = "fill" if "[SUCCESS]" in result else "warn"
                await websocket.send(json.dumps({"type": "LOG", "text": result, "category": category}))
    except:
        pass
    finally:
        connected_clients.remove(websocket)

async def main():
    port = int(os.environ.get("PORT", 10000))
    async with websockets.serve(handle_messages, "0.0.0.0", port, process_request=health_check):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
