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
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
solana_client = Client(SOLANA_RPC_URL)

bot_keypair = None
if SOLANA_PRIVATE_KEY:
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))
            bot_keypair = Keypair.from_bytes(key_bytes)
        else:
            bot_keypair = Keypair.from_bytes(base58.b58decode(SOLANA_PRIVATE_KEY))
        print(f"[SYSTEM] Wallet reale caricato: {bot_keypair.pubkey()}")
    except Exception as e:
        print(f"[ERROR] Errore caricamento chiave privata: {e}")

connected_clients = set()

async def health_check(path, request_headers):
    if "Upgrade" not in request_headers.get("connection", "").lower() and \
       "websocket" not in request_headers.get("upgrade", "").lower():
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"Grok Bot Backend is Alive!"

async def execute_real_solana_buy():
    """ Esegue un acquisto REALE On-Chain di $USDC tramite Jupiter DEX per 0.01 SOL """
    if not bot_keypair:
        return "[ERROR] Nessuna chiave privata trovata su Render! Configura SOLANA_PRIVATE_KEY."

    try:
        user_pubkey = str(bot_keypair.pubkey())
        # Token Mints: SOL e USDC
        input_mint = "So11111111111111111111111111111111111111112"
        output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC Mainnet
        amount_lamports = 10000000  # 0.01 SOL per il test reale

        # 1. Richiedi la Quote a Jupiter API
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=100"
        quote_res = requests.get(quote_url).json()

        if "error" in quote_res:
            return f"[ERROR] Errore Quote Jupiter: {quote_res.get('error')}"

        # 2. Richiedi la transazione da firmare a Jupiter
        swap_url = "https://quote-api.jup.ag/v6/swap"
        payload = {
            "quoteResponse": quote_res,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True
        }
        swap_res = requests.post(swap_url, json=payload).json()
        swap_transaction_b64 = swap_res.get("swapTransaction")

        if not swap_transaction_b64:
            return "[ERROR] Impossibile recuperare la transazione da Jupiter."

        # 3. Decodifica e Firma la Transazione con la tua Chiave Privata
        raw_tx = base64.b64decode(swap_transaction_b64)
        tx = VersionedTransaction.from_bytes(raw_tx)

        # Firma la transazione con la tua keypair
        signature = bot_keypair.sign_message(tx.message.to_bytes())
        signed_tx = VersionedTransaction.populate(tx.message, [signature])

        # 4. Invia la transazione sulla Blockchain Solana
        tx_hash = solana_client.send_raw_transaction(bytes(signed_tx)).value

        return f"[SUCCESS] ACQUISTO REALE ESEGUITO! Tx Hash: {tx_hash}"

    except Exception as e:
        return f"[ERROR] Transazione fallita: {str(e)}"

async def register(websocket):
    connected_clients.add(websocket)
    await websocket.send(json.dumps({
        "type": "LOG",
        "text": f"[SYSTEM] Connesso. Wallet di trading attivo: {bot_keypair.pubkey() if bot_keypair else 'Nessuno'}",
        "category": "info"
    }))

async def unregister(websocket):
    connected_clients.remove(websocket)

async def handle_messages(websocket, path):
    await register(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "FORCE_BUY":
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": "[EXEC] Invio ordine di acquisto REALE a Jupiter DEX in corso...",
                    "category": "exec"
                }))
                
                # Esegue la transazione sulla blockchain
                result = await execute_real_solana_buy()
                
                category = "fill" if "[SUCCESS]" in result else "warn"
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": result,
                    "category": category
                }))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await unregister(websocket)

async def main():
    port = int(os.environ.get("PORT", 10000))
    async with websockets.serve(handle_messages, "0.0.0.0", port, process_request=health_check):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
