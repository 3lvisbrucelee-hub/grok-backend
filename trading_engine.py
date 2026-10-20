import os
import json
import base64
import base58
from flask import Flask, jsonify, request
from flask_cors import CORS
from cryptography.hazmat.primitives.asymmetric import ed25519
import requests

app = Flask(__name__)
CORS(app)  # Abilita le richieste dal frontend Vercel

SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

def get_bot_credentials():
    if not SOLANA_PRIVATE_KEY:
        return None, None
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))[:32]
        else:
            key_bytes = base58.b58decode(SOLANA_PRIVATE_KEY)[:32]
            
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
        pub_bytes = private_key.public_key().public_bytes_raw()
        pubkey_b58 = base58.b58encode(pub_bytes).decode('utf-8')
        return private_key, pubkey_b58
    except Exception as e:
        print(f"[ERROR] Chiave privata non valida: {e}")
        return None, None

@app.route("/", methods=["GET"])
def health_check():
    _, pubkey = get_bot_credentials()
    status = "Online" if pubkey else "Online (Senza Chiave)"
    return jsonify({"status": status, "wallet": pubkey}), 200

@app.route("/api/trade", methods=["POST"])
def execute_trade():
    private_key, pubkey_b58 = get_bot_credentials()
    if not private_key or not pubkey_b58:
        return jsonify({"success": False, "message": "Errore: Chiave privata non configurata su Render!"}), 400

    data = request.get_json() or {}
    action = data.get("action")

    if action == "FORCE_BUY":
        try:
            input_mint = "So11111111111111111111111111111111111111112"  # SOL
            output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC
            amount_lamports = 5000000  # 0.005 SOL

            # 1. Preventivo Jupiter
            quote_res = requests.get(
                f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=200",
                timeout=10
            ).json()
            
            if "error" in quote_res:
                return jsonify({"success": False, "message": f"Jupiter Quote Error: {quote_res.get('error')}"}), 400

            # 2. Transazione di Swap
            swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
                "quoteResponse": quote_res,
                "userPublicKey": pubkey_b58,
                "wrapAndUnwrapSol": True
            }, timeout=10).json()

            swap_tx_b64 = swap_res.get("swapTransaction")
            if not swap_tx_b64:
                return jsonify({"success": False, "message": "Impossibile generare la transazione da Jupiter."}), 400

            # 3. Firma crittografica
            tx_bytes = bytearray(base64.b64decode(swap_tx_b64))
            num_signatures = tx_bytes[0]
            msg_offset = 1 + (num_signatures * 64)
            message_bytes = bytes(tx_bytes[msg_offset:])
            
            signature = private_key.sign(message_bytes)
            tx_bytes[1:65] = signature
            signed_tx_b64 = base64.b64encode(bytes(tx_bytes)).decode('utf-8')

            # 4. Invio alla rete Solana
            rpc_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [signed_tx_b64, {"encoding": "base64", "skipPreflight": True}]
            }
            rpc_res = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload, timeout=10).json()

            if "result" in rpc_res:
                return jsonify({"success": True, "message": f"ACQUISTO ESEGUITO! Tx: {rpc_res['result']}"}), 200
            else:
                err_msg = rpc_res.get("error", {}).get("message", "Rifiutato dalla rete")
                return jsonify({"success": False, "message": f"Errore Solana: {err_msg}"}), 400

        except Exception as e:
            return jsonify({"success": False, "message": f"Errore interno: {str(e)}"}), 500

    return jsonify({"success": False, "message": "Azione non riconosciuta"}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
