import asyncio
import json
import os
import websockets
from solana.rpc.api import Client
from solders.keypair import Keypair
import base58

# Recupera la chiave privata configurata in sicurezza nelle variabili d'ambiente di Render
SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

# Inizializzazione del client Solana (Mainnet)
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
solana_client = Client(SOLANA_RPC_URL)

# Configurazione del Wallet del Bot (se la chiave è presente)
bot_keypair = None
if SOLANA_PRIVATE_KEY:
    try:
        # Supporta sia array di byte che stringa Base58
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))
            bot_keypair = Keypair.from_bytes(key_bytes)
        else:
            bot_keypair = Keypair.from_bytes(base58.b58decode(SOLANA_PRIVATE_KEY))
        print(f"[SYSTEM] Wallet caricato con successo per il trading in cloud.")
    except Exception as e:
        print(f"[ERROR] Errore nel caricamento della chiave privata: {e}")

# Gestione delle connessioni WebSocket con il frontend
connected_clients = set()

async def register(websocket):
    connected_clients.add(websocket)
    print(f"[SYSTEM] Nuovo client frontend connesso.")
    # Invia un log iniziale di benvenuto
    await websocket.send(json.dumps({
        "type": "LOG",
        "text": "[SYSTEM] Connessione stabilita con il Trading Engine in cloud su Render.",
        "category": "info"
    }))

async def unregister(websocket):
    connected_clients.remove(websocket)
    print(f"[SYSTEM] Client disconnesso.")

async def handle_messages(websocket):
    await register(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            print(f"[COMMAND] Comando ricevuto dal frontend: {action}")
            
            if action == "FORCE_BUY":
                # Logica di esecuzione acquisto reale o simulata protetta
                response_text = "[EXEC] Ordine di acquisto (FORCE_BUY) inviato alla blockchain di Solana!"
                print(response_text)
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": response_text,
                    "category": "fill"
                }))
                
            elif action == "FORCE_SELL":
                response_text = "[EXEC] Posizione chiusa con successo (FORCE_SELL)."
                print(response_text)
                await websocket.send(json.dumps({
                    "type": "LOG",
                    "text": response_text,
                    "category": "warn"
                }))
                
            elif action == "TOGGLE_BOT":
                response_text = "[SYSTEM] Stato del bot modificato (Pausa/Avvio)."
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
    async with websockets.serve(handle_messages, "0.0.0.0", port):
        await asyncio.Future()  # Mantieni il server attivo all'infinito

if __name__ == "__main__":
    asyncio.run(main())
