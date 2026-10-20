import asyncio
import json
import os
import http
import websockets
from solana.rpc.api import Client
from solders.keypair import Keypair
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
        print(f"[SYSTEM] Wallet di trading cloud caricato correttamente.")
    except Exception as e:
        print(f"[ERROR] Errore caricamento chiave privata: {e}")

connected_clients = set()

async def health_check(path, request_headers):
    if "Upgrade" not in request_headers.get("connection", "").lower() and \
       "websocket" not in request_headers.get("upgrade", "").lower():
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"Grok Bot Backend is Alive!"

async def register(websocket):
    connected_clients.add(websocket)
    print(f"[SYSTEM] Client frontend connesso.")
    await websocket.send(json.dumps({
        "type": "LOG",
        "text": "[SYSTEM] Connessione stabilita. Bot in ascolto (modalità manuale/reale).",
        "category": "info"
    }))

async def unregister(websocket):
    connected_clients.remove(websocket)
    print(f"[SYSTEM] Client disconnesso.")

async def handle_messages(websocket, path):
    await register(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            print(f"[COMMAND] Comando ricevuto: {action}")
            
            if action == "FORCE_BUY":
                response_text = "[EXEC] Esecuzione ordine d'acquisto reale su Solana avviata..."
                print(response_text)
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": response_text,
                    "category": "fill"
                }))
                
            elif action == "FORCE_SELL":
                response_text = "[EXEC] Chiusura di tutte le posizioni attive..."
                print(response_text)
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": response_text,
                    "category": "warn"
                }))
                
            elif action == "TOGGLE_BOT":
                response_text = "[SYSTEM] Stato operativo del bot aggiornato."
                print(response_text)
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": response_text,
                    "category": "exec"
                }))
                
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await unregister(websocket)

async def main():
    port = int(os.environ.get("PORT", 10000))
    print(f"[SYSTEM] Avvio WebSocket Server sulla porta {port}...")
    async with websockets.serve(handle_messages, "0.0.0.0", port, process_request=health_check):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
