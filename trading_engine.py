import asyncio
import json
import os
import http
import websockets
import requests
import base64
import base58
from nacl.signing import SigningKey

SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

def get_signing_key():
    if not SOLANA_PRIVATE_KEY:
        return None
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))
            return SigningKey(key_bytes[:32])
        else:
            decoded = base58.b58decode(SOLANA_PRIVATE_KEY)
            return SigningKey(decoded[:32])
    except Exception as e:
        print(f"[ERROR] Errore chiave privata: {e}")
        return None

connected_clients = set()

async def health_check(path, request_headers):
    if "Upgrade" not in request_headers.get("connection", "").lower() and \
       "websocket" not in request_headers.get("upgrade", "").lower():
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"Grok Bot Backend is Alive!"

async def execute_real_swap():
    signer = get_signing_key()
    if not signer:
        return "[ERROR] Chiave privata mancante o non valida su Render!"

    try:
        from solders.keypair import Keypair
        # Conversione sicura per le API di Jupiter
        raw_bytes = bytes(signer.encode() + signer.verify_key.encode())
        bot_kp = Keypair.from_bytes(raw_bytes)
        user_pubkey = str(bot_kp.pubkey())

        input_mint = "So11111111111111111111111111111111111111112" # SOL
        output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC
        amount_lamports = 5000000 # 0.005 SOL

        # 1. Richiesta a Jupiter DEX
        quote_res = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=200").json()
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

        # 2. Firma e invio transazione reale
        from solders.transaction import VersionedTransaction
        raw_tx = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(raw_tx)
        signature = bot_kp.sign_message(tx.message.to_bytes())
        signed_tx = VersionedTransaction.populate(tx.message, [signature])

        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(bytes(signed_tx)).decode('utf-8'), {"encoding": "base64"}]
        }
        res = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload).json()

        if "result" in res:
            return f"[SUCCESS] SWAP REALE ESEGUITO! Tx: {res['result']}"
        else:
            return f"[ERROR] Rifiutato dalla rete: {res.get('error', {}).get('message', 'Unknown')}"

    except Exception as e:
        return f"[ERROR] Fallito: {str(e)}"

async def handle_messages(websocket, path):
    connected_clients.add(websocket)
    try:
        await websocket.send(json.dumps({"type": "LOG", "text": "[SYSTEM] Connesso al server cloud in modo stabile.", "category": "info"}))
        async for message in websocket:
            data = json.loads(message)
            if data.get("action") == "FORCE_BUY":
                await websocket.send(json.dumps({"type": "LOG", "text": "[EXEC] Invio ordine automatico a Jupiter DEX...", "category": "exec"}))
                result = await execute_real_swap()
                category = "fill" if "[SUCCESS]" in result else "warn"
                await websocket.send(json.dumps({"type": "LOG", "text": result, "category": category}))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)

async def main():
    port = int(os.environ.get("PORT", 10000))
    print(f"[SYSTEM] Avvio server sulla porta {port}...")
    async with websockets.serve(handle_messages, "0.0.0.0", port, process_request=health_check):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
