import asyncio
import json
import os
import http
import random
import websockets
import requests
import base64
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
        print(f"[SYSTEM] Wallet bot caricato con successo: {bot_keypair.pubkey()}")
    except Exception as e:
        print(f"[ERROR] Errore caricamento chiave privata: {e}")

connected_clients = set()

async def health_check(path, request_headers):
    if "Upgrade" not in request_headers.get("connection", "").lower() and \
       "websocket" not in request_headers.get("upgrade", "").lower():
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"Grok Bot Backend is Alive!"

async def execute_automated_jupiter_buy():
    """ Esegue un acquisto REALE automatico tramite Jupiter DEX con i fondi del wallet cloud """
    if not bot_keypair:
        return "[ERROR] Chiave privata non configurata su Render!"

    try:
        user_pubkey = str(bot_keypair.pubkey())
        input_mint = "So11111111111111111111111111111111111111112" # SOL
        output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC (o un token di test sicuro)
        amount_lamports = 5000000  # 0.005 SOL per test automatico sicuro

        # 1. Ottieni la quota da Jupiter DEX API
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=200"
        quote_res = requests.get(quote_url).json()
        
        if "error" in quote_res:
            return f"[ERROR] Jupiter Quote fallita: {quote_res.get('error')}"

        # 2. Ottieni la transazione di swap
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote_res,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True
        }).json()

        swap_tx_b64 = swap_res.get("swapTransaction")
        if not swap_tx_b64:
            return "[ERROR] Impossibile generare la transazione di swap automatico."

        # 3. Firma la transazione con la chiave privata del bot
        raw_tx = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(raw_tx)
        signature = bot_keypair.sign_message(tx.message.to_bytes())
        signed_tx = VersionedTransaction.populate(tx.message, [signature])

        # 4. Invia la transazione direttamente sulla blockchain di Solana
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(bytes(signed_tx)).decode('utf-8'), {"encoding": "base64"}]
        }
        res = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload).json()

        if "result" in res:
            return f"[SUCCESS] BOT AUTONOMO: Acquisto reale eseguito! Tx: {res['result']}"
        else:
            return f"[ERROR] Transazione rifiutata dalla rete: {res.get('error', {}).get('message', 'Unknown')}"

    except Exception as e:
        return f"[ERROR] Eccezione nello swap automatico: {str(e)}"

async def register(websocket):
    connected_clients.add(websocket)
    await websocket.send(json.dumps({
        "type": "LOG",
        "text": f"[SYSTEM] Bot autonomo connesso. Wallet operativo pronto.",
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
            
            print(f"[COMMAND] Ricevuto comando dashboard: {action}")
            
            if action == "FORCE_BUY":
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": "[EXEC] Il bot sta eseguendo l'acquisto REALE automatico su Solana...",
                    "category": "exec"
                }))
                
                # Esegue lo swap reale in autonomia
                result = await execute_automated_jupiter_buy()
                category = "fill" if "[SUCCESS]" in result else "warn"
                
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": result,
                    "category": category
                }))
                
            elif action == "FORCE_SELL":
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": "[EXEC] Bot: Chiusura forzata posizioni in corso...",
                    "category": "warn"
                }))
                
            elif action == "TOGGLE_BOT":
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": "[SYSTEM] Stato del bot autonomo aggiornato.",
                    "category": "exec"
                }))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await unregister(websocket)

async def main():
    port = int(os.environ.get("PORT", 10000))
    print(f"[SYSTEM] Avvio Backend Bot Autonomo sulla porta {port}...")
    
    async with websockets.serve(handle_messages, "0.0.0.0", port, process_request=health_check):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
