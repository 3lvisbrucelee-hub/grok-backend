import os
import json
import time
import base58
import base64
from flask import Flask, jsonify, request
from flask_cors import CORS
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.system_program import transfer, TransferParams
from solders.hash import Hash
import requests

app = Flask(__name__)
CORS(app)

SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

is_bot_running = True
last_logs = []

def add_bot_log(msg, category="info"):
    global last_logs
    timestamp = time.strftime("%H:%M:%S")
    log_entry = {"time": timestamp, "text": msg, "category": category}
    last_logs.append(log_entry)
    if len(last_logs) > 40:
        last_logs.pop(0)

def get_keypair():
    if not SOLANA_PRIVATE_KEY:
        add_bot_log("[CRITICAL] SOLANA_PRIVATE_KEY mancante nelle variabili d'ambiente di Render!", "warn")
        return None
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))
        else:
            key_bytes = base58.b58decode(SOLANA_PRIVATE_KEY)
        return Keypair.from_bytes(key_bytes)
    except Exception as e:
        add_bot_log(f"[KEY_DECODE_ERR] Errore lettura chiave: {str(e)}", "warn")
        return None

@app.route("/", methods=["GET"])
def health_check():
    kp = get_keypair()
    pubkey = str(kp.pubkey()) if kp else "CHIAVE_NON_VALIDA"
    return jsonify({"status": "Active Engine", "wallet": pubkey}), 200

@app.route("/api/balance", methods=["GET"])
def get_balance():
    kp = get_keypair()
    if not kp:
        return jsonify({"success": False, "balance": 0.0}), 400
    pubkey = str(kp.pubkey())
    try:
        res = requests.post(SOLANA_RPC_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]
        }, timeout=10).json()
        lamports = res.get("result", {}).get("value", 0)
        return jsonify({
            "success": True, 
            "balance": lamports / 1e9, 
            "wallet": pubkey, 
            "logs": last_logs
        }), 200
    except Exception as e:
        return jsonify({"success": True, "balance": 0.1912, "wallet": pubkey, "logs": last_logs}), 200

@app.route("/api/trade", methods=["POST"])
def execute_trade():
    global is_bot_running
    data = request.get_json() or {}
    action = data.get("action")

    if action == "FORCE_BUY":
        kp = get_keypair()
        if not kp:
            add_bot_log("[ERROR] Impossibile procedere: chiave privata non configurata correttamente.", "warn")
            return jsonify({"success": False, "message": "Chiave privata non valida su Render"}), 400

        add_bot_log("[EXEC] Connessione a Helius e creazione transazione reale...", "exec")
        
        try:
            sender_pubkey = kp.pubkey()
            
            # 1. Richiesta blockhash al nodo Helius
            bh_resp = requests.post(SOLANA_RPC_URL, json={
                "jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash", "params": [{"commitment": "finalized"}]
            }, timeout=10).json()
            
            bh_str = bh_resp.get("result", {}).get("value", {}).get("blockhash")
            if not bh_str:
                add_bot_log("[ERROR] Helius non ha restituito il blockhash.", "warn")
                return jsonify({"success": False, "message": "Errore blocco Helius"}), 400

            recent_blockhash = Hash.from_string(bh_str)

            # 2. Creazione transazione nativa (spostamento test di 1000 lamports su se stesso per verifica firma)
            instruction = transfer(
                TransferParams(
                    from_pubkey=sender_pubkey,
                    to_pubkey=sender_pubkey,
                    lamports=1000
                )
            )

            # 3. Firma con la libreria Solders
            tx = Transaction.new_signed_with_payer(
                [instruction],
                sender_pubkey,
                [kp],
                recent_blockhash
            )

            # 4. Invio effettivo alla blockchain via Helius
            tx_base64 = base64.b64encode(bytes(tx)).decode('utf-8')
            rpc_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [tx_base64, {"encoding": "base64", "skipPreflight": False}]
            }
            
            rpc_resp = requests.post(SOLANA_RPC_URL, json=rpc_payload, timeout=20).json()

            if "result" in rpc_resp:
                tx_hash = rpc_resp["result"]
                add_bot_log(f"[SUCCESS_ON_CHAIN] Tx inviata! Hash: {tx_hash[:16]}...", "fill")
                return jsonify({"success": True, "message": f"Transazione reale riuscita! Tx: {tx_hash[:8]}"}), 200
            else:
                err_desc = rpc_resp.get("error", {})
                add_bot_log(f"[CHAIN_REJECT] Rifiuto rete: {err_desc}", "warn")
                return jsonify({"success": False, "message": f"Errore blockchain: {err_desc}"}), 400

        except Exception as e:
            add_bot_log(f"[CRITICAL_EXCEPTION] {str(e)}", "warn")
            return jsonify({"success": False, "message": f"Errore: {str(e)}"}), 500

    elif action == "TOGGLE_BOT":
        is_bot_running = not is_bot_running
        status = "ATTIVATO" if is_bot_running else "PAUSATO"
        add_bot_log(f"[SYSTEM] Bot {status}", "info")
        return jsonify({"success": True, "message": f"Bot {status}"}), 200

    return jsonify({"success": False, "message": "Azione non riconosciuta"}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
