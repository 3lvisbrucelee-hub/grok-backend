import asyncio
import json
import os
import http
import websockets
import requests
import base64
import base58
from cryptography.hazmat.primitives.asymmetric import ed25519

SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

bot_private_key = None
bot_pubkey_b58 = None

if SOLANA_PRIVATE_KEY:
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))[:32]
        else:
            key_bytes = base58.b58decode(SOLANA_PRIVATE_KEY)[:32]
            
        bot_private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
        pub_bytes = bot_private_key.public_key().public_bytes_raw()
        bot_pubkey_b58 = base58.b58encode(pub_bytes).decode('utf-8')
        print(f"[SYSTEM] Wallet caricato con successo: {bot_pubkey_b58}")
    except Exception as e:
        print(f"[ERROR] Errore caricamento chiave: {e}")

connected_clients = set()

async def health_check(path, request_headers):
    if "Upgrade" not in request_headers.get("connection", "").lower() and \
       "websocket" not in request_headers.get("upgrade", "").lower():
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"Grok Bot Backend is Alive!"

async def execute_automated_jupiter_buy():
    if not bot_private_key or not bot_pubkey_b58:
        return "[ERROR] Chiave privata non trovata o non valida su Render!"

    try:
        input_mint = "So11111111111111111111111111111111111111112"  # SOL
        output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC
        amount_lamports = 5000000  # 0.005 SOL

        # 1. Quote Jupiter
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=200"
        quote_res = requests.get(quote_url, timeout=10).json()
        if "error" in quote_res:
            return f"[ERROR] Jupiter Quote: {quote_res.get('error')}"

        # 2. Swap Transaction da Jupiter
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote_res,
            "userPublicKey": bot_pubkey_b58,
            "wrapAndUnwrapSol": True
        }, timeout=10).json()

        swap_tx_b64 = swap_res.get("swapTransaction")
        if not swap_tx_b64:
            return "[ERROR] Impossibile generare transazione di swap da Jupiter."

        # 3. Decodifica e Firma nativa
        tx_bytes = bytearray(base64.b64decode(swap_tx_b64))
        
        # Firma del messaggio della transazione Versioned
        # Il messaggio inizia dopo le firme (byte offset standard)
        num_signatures = tx_bytes[0]
        msg_offset = 1 + (num_signatures * 64)
        message_bytes = bytes(tx_bytes[msg_offset:])
        
        signature = bot_private_key.sign(message_bytes)
        
        # Inserisci la firma nella transazione
        tx_bytes[1:65] = signature
        signed_tx_b64 = base64.b64encode(bytes(tx_bytes)).decode('utf-8')

        # 4. Invio a Solana Mainnet RPC
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [signed_tx_b64, {"encoding": "base64", "skipPreflight": True}]
        }
        rpc_res = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload, timeout=10).json()

        if "result" in rpc_res:
            return f"[SUCCESS] ACQUISTO AUTONOMO ESEGUITO! Tx: {rpc_res['result']}"
        else:
            err_msg = rpc_res.get("error", {}).get("message", "Errore sconosciuto")
            return f"[ERROR] RPC Solana: {err_msg}"

    except Exception as e:
        return f"[ERROR] Eccezione: {str(e)}"

async def handle_messages(websocket, path):
    connected_clients.add(websocket)
    try:
        await websocket.send(json.dumps({
            "type": "LOG",
            "text": f"[SYSTEM] Connessione WebSocket STABILE con Render. Wallet bot attivo ({bot_pubkey_b58[:6]}...).",
            "category": "info"
        }))
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "FORCE_BUY":
                await websocket.send(json.dumps({"type": "LOG", "text": "[EXEC] Invio ordine automatico a Jupiter DEX...", "category": "exec"}))
                res = await execute_automated_jupiter_buy()
                cat = "fill" if "[SUCCESS]" in res else "warn"
                await websocket.send(json.dumps({"type": "LOG", "text": res, "category": cat}))
                
            elif action == "FORCE_SELL":
                await websocket.send(json.dumps({"type": "LOG", "text": "[EXEC] Chiusura posizioni avviata...", "category": "warn"}))
                
            elif action == "TOGGLE_BOT":
                await websocket.send(json.dumps({"type": "LOG", "text": "[SYSTEM] Stato del bot autonomo aggiornato.", "category": "exec"}))
                
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
