import os
import json
import base58
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

SOLANA_PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

def get_pubkey():
    if not SOLANA_PRIVATE_KEY:
        return None
    try:
        if SOLANA_PRIVATE_KEY.startswith("["):
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))[:32]
        else:
            key_bytes = base58.b58decode(SOLANA_PRIVATE_KEY)[:32]
        # Deriva la public key da base58 o ed25519
        from cryptography.hazmat.primitives.asymmetric import ed25519
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
        pub_bytes = private_key.public_key().public_bytes_raw()
        return base58.b58encode(pub_bytes).decode('utf-8')
    except Exception as e:
        print(f"[ERROR] Chiave: {e}")
        return None

@app.route("/", methods=["GET"])
def health_check():
    pubkey = get_pubkey()
    return jsonify({"status": "Online", "wallet": pubkey}), 200

@app.route("/api/balance", methods=["GET"])
def get_balance():
    pubkey = get_pubkey()
    if not pubkey:
        return jsonify({"success": False, "balance": 0.0}), 400
    
    try:
        # Richiesta RPC ufficiale Solana via HTTP (senza blocchi CORS)
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [pubkey]
        }
        res = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload, timeout=5).json()
        lamports = res.get("result", {}).get("value", 0)
        sol_balance = lamports / 1e9
        return jsonify({"success": True, "balance": sol_balance, "wallet": pubkey}), 200
    except Exception as e:
        return jsonify({"success": False, "balance": 0.0, "error": str(e)}), 500

@app.route("/api/trade", methods=["POST"])
def execute_trade():
    pubkey = get_pubkey()
    if not pubkey:
        return jsonify({"success": False, "message": "Chiave privata non configurata su Render!"}), 400

    data = request.get_json() or {}
    action = data.get("action")

    if action == "FORCE_BUY":
        try:
            input_mint = "So11111111111111111111111111111111111111112"  # SOL
            output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC
            amount_lamports = 5000000  # 0.005 SOL

            quote_res = requests.get(
                f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=200",
                timeout=10
            ).json()
            
            if "error" in quote_res:
                return jsonify({"success": False, "message": f"Jupiter Error: {quote_res.get('error')}"}), 400

            swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
                "quoteResponse": quote_res,
                "userPublicKey": pubkey,
                "wrapAndUnwrapSol": True
            }, timeout=10).json()

            swap_tx_b64 = swap_res.get("swapTransaction")
            if not swap_tx_b64:
                return jsonify({"success": False, "message": "Impossibile generare lo swap."}), 400

            # Firma e invio standard
            import base64
            from cryptography.hazmat.primitives.asymmetric import ed25519
            key_bytes = bytes(json.loads(SOLANA_PRIVATE_KEY))[:32] if SOLANA_PRIVATE_KEY.startswith("[") else base58.b58decode(SOLANA_PRIVATE_KEY)[:32]
            private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)

            tx_bytes = bytearray(base64.b64decode(swap_tx_b64))
            num_signatures = tx_bytes[0]
            msg_offset = 1 + (num_signatures * 64)
            message_bytes = bytes(tx_bytes[msg_offset:])
            
            signature = private_key.sign(message_bytes)
            tx_bytes[1:65] = signature
            signed_tx_b64 = base64.b64encode(bytes(tx_bytes)).decode('utf-8')

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
            return jsonify({"success": False, "message": f"Errore: {str(e)}"}), 500

    return jsonify({"success": False, "message": "Azione non riconosciuta"}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
