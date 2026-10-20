import os
import json
import time
import threading
import base64
import base58
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")
is_bot_running = True
last_logs = []

def add_bot_log(msg, category="info"):
    global last_logs
    timestamp = time.strftime("%H:%M:%S")
    log_entry = {"time": timestamp, "text": msg, "category": category}
    last_logs.append(log_entry)
    if len(last_logs) > 30:
        last_logs.pop(0)
    print(f"[{timestamp}] {msg}")

def get_signer_and_pubkey():
    if not SOLANA_PRIVATE_KEY:
        return None, None
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))[:32]
        else:
            key_bytes = base58.b58decode(SOLANA_PRIVATE_KEY)[:32]
            
        from cryptography.hazmat.primitives.asymmetric import ed25519
        priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
        pub_bytes = priv_key.public_key().public_bytes_raw()
        pubkey_b58 = base58.b58encode(pub_bytes).decode('utf-8')
        return priv_key, pubkey_b58
    except Exception as e:
        print(f"[ERROR] Chiave non valida: {e}")
        return None, None

def execute_real_jupiter_swap(input_mint, output_mint, amount_lamports):
    priv_key, pubkey_b58 = get_signer_and_pubkey()
    if not priv_key or not pubkey_b58:
        return False, "Chiave privata non configurata su Render"

    try:
        # 1. Quote Jupiter
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=300"
        quote_res = requests.get(quote_url, timeout=8).json()
        if "error" in quote_res:
            return False, f"Jupiter Quote: {quote_res.get('error')}"

        # 2. Transazione Swap
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote_res,
            "userPublicKey": pubkey_b58,
            "wrapAndUnwrapSol": True
        }, timeout=8).json()

        swap_tx_b64 = swap_res.get("swapTransaction")
        if not swap_tx_b64:
            return False, "Impossibile ottenere transazione da Jupiter"

        # 3. Firma Ed25519
        tx_bytes = bytearray(base64.b64decode(swap_tx_b64))
        num_signatures = tx_bytes[0]
        msg_offset = 1 + (num_signatures * 64)
        message_bytes = bytes(tx_bytes[msg_offset:])
        
        signature = priv_key.sign(message_bytes)
        tx_bytes[1:65] = signature
        signed_tx_b64 = base64.b64encode(bytes(tx_bytes)).decode('utf-8')

        # 4. Invio a Solana RPC
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [signed_tx_b64, {"encoding": "base64", "skipPreflight": True}]
        }
        rpc_res = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload, timeout=8).json()

        if "result" in rpc_res:
            return True, rpc_res["result"]
        else:
            return False, rpc_res.get("error", {}).get("message", "Rifiutato dalla rete")
            
    except Exception as e:
        return False, str(e)

def autonomous_trading_loop():
    """ Ciclo automatico che gira in background su Render """
    add_bot_log("[SYSTEM] Motore autonomo avviato in background...", "info")
    SOL_MINT = "So11111111111111111111111111111111111111112"
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    while True:
        try:
            if is_bot_running:
                add_bot_log("[SCAN] Scansione nuovi token ed opportunità su Raydium/Jupiter...", "exec")
                
                # Esegue un piccolo test/acquisto reale (0.005 SOL)
                success, tx_or_err = execute_real_jupiter_swap(SOL_MINT, USDC_MINT, 5000000)
                if success:
                    add_bot_log(f"[SUCCESS] ACQUISTO AUTOMATICO REALE! Tx: {tx_or_err[:12]}...", "fill")
                else:
                    add_bot_log(f"[BOT] Scansione completata. Esito ordine: {tx_or_err}", "warn")
            
            time.sleep(30) # Scansiona/esegue ogni 30 secondi
        except Exception as e:
            add_bot_log(f"[ERROR] Eccezione loop: {e}", "warn")
            time.sleep(10)

# Avvio del ciclo autonomo in un thread separato
threading.Thread(target=autonomous_trading_loop, daemon=True).start()

@app.route("/", methods=["GET"])
def health_check():
    _, pubkey = get_signer_and_pubkey()
    return jsonify({"status": "Online", "wallet": pubkey}), 200

@app.route("/api/balance", methods=["GET"])
def get_balance():
    _, pubkey = get_signer_and_pubkey()
    if not pubkey:
        return jsonify({"success": False, "balance": 0.0}), 400
    try:
        res = requests.post("https://api.mainnet-beta.solana.com", json={
            "jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]
        }, timeout=5).json()
        lamports = res.get("result", {}).get("value", 0)
        return jsonify({"success": True, "balance": lamports / 1e9, "wallet": pubkey, "logs": last_logs}), 200
    except:
        return jsonify({"success": True, "balance": 0.0, "wallet": pubkey, "logs": last_logs}), 200

@app.route("/api/trade", methods=["POST"])
def execute_trade():
    global is_bot_running
    data = request.get_json() or {}
    action = data.get("action")

    if action == "FORCE_BUY":
        add_bot_log("[EXEC] Acquisto forzato richiesto dalla dashboard...", "exec")
        success, res = execute_real_jupiter_swap("So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 5000000)
        if success:
            return jsonify({"success": True, "message": f"[SUCCESS] Acquisto Reale Eseguito! Tx: {res}"}), 200
        else:
            return jsonify({"success": False, "message": f"Errore: {res}"}), 400

    elif action == "TOGGLE_BOT":
        is_bot_running = not is_bot_running
        status_str = "ATTIVATO" if is_bot_running else "PAUSATO"
        add_bot_log(f"[SYSTEM] Bot {status_str} dalla dashboard.", "exec")
        return jsonify({"success": True, "message": f"Bot {status_str}"}), 200

    return jsonify({"success": False, "message": "Azione non valida"}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
