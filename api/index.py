from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import hashlib
import json
import plotly.express as px
import plotly.graph_objects as go
import base64
import io

app = Flask(__name__)

# ------------------------------------------------------------------
# GLOBAL CONSTANTS (same as Streamlit)
# ------------------------------------------------------------------
CRYPTO_COINS = ["bitcoin", "ethereum", "ripple", "cardano", "solana"]
CRYPTO_NAMES = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP",
                "cardano": "ADA", "solana": "SOL"}

# ------------------------------------------------------------------
# SIMULATED DATABASE (in-memory dicts – no SQLite, Vercel safe)
# ------------------------------------------------------------------
users_db = {"admin": {"password": hashlib.sha256("admin123".encode()).hexdigest(), "role": "admin", "email": "admin@example.com"},
            "guest": {"password": "", "role": "guest", "email": ""},
            "demo": {"password": hashlib.sha256("demo".encode()).hexdigest(), "role": "user", "email": "demo@example.com"}}
wallets = {}          # username: balance
trades = []           # list of trade dicts
alerts_list = []      # list of alert dicts

def get_balance(username):
    return wallets.get(username, 10000.0)   # default $10k for guest

def update_balance(username, amount):
    wallets[username] = wallets.get(username, 10000.0) + amount

# ------------------------------------------------------------------
# FOREX ENGINE (same logic, returns DataFrames)
# ------------------------------------------------------------------
class ForexEngine:
    PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "UGX/USD", "KES/USD", "SSP/USD"]

    @staticmethod
    def fetch_latest_rates():
        try:
            resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
            resp.raise_for_status()
            data = resp.json()["rates"]
            live = {}
            pair_map = {"EUR/USD": "EUR", "GBP/USD": "GBP", "USD/JPY": "JPY",
                        "UGX/USD": "UGX", "KES/USD": "KES", "SSP/USD": "SSP"}
            for pair, code in pair_map.items():
                if code in data:
                    if pair in ["EUR/USD", "GBP/USD"]:
                        live[pair] = round(1 / data[code], 4)
                    else:
                        live[pair] = round(data[code], 4)
            return live
        except:
            return None

    @staticmethod
    def get_live_data(use_real=True):
        if use_real:
            live = ForexEngine.fetch_latest_rates()
            if live is not None:
                np.random.seed(42)
                times = [datetime.now() - timedelta(minutes=i) for i in range(60)][::-1]
                df = pd.DataFrame({"Time": times})
                defaults = {"EUR/USD":1.08,"GBP/USD":1.26,"USD/JPY":144.5,
                            "UGX/USD":3750,"KES/USD":145,"SSP/USD":1100}
                for pair in ForexEngine.PAIRS:
                    base = live.get(pair, defaults[pair])
                    vol = base * 0.0002
                    prices = base + np.cumsum(np.random.normal(0, vol, 60))
                    df[pair] = np.round(np.maximum(prices, 0.0001), 4)
                return df, live
        return ForexEngine.simulated_data()

    @staticmethod
    def simulated_data():
        np.random.seed(42)
        times = [datetime.now() - timedelta(minutes=i) for i in range(60)][::-1]
        base = {"EUR/USD":1.08,"GBP/USD":1.26,"USD/JPY":144.5,
                "UGX/USD":3750,"KES/USD":145,"SSP/USD":1100}
        vol = {"EUR/USD":0.0003,"GBP/USD":0.0004,"USD/JPY":0.02,
               "UGX/USD":2,"KES/USD":0.1,"SSP/USD":5}
        data = {"Time": times}
        for pair in ForexEngine.PAIRS:
            data[pair] = np.round(base[pair] + np.cumsum(np.random.normal(0, vol[pair], 60)), 4)
        return pd.DataFrame(data), base

# ------------------------------------------------------------------
# CRYPTO ENGINE
# ------------------------------------------------------------------
class CryptoEngine:
    @staticmethod
    def fetch_prices():
        try:
            ids = ",".join(CRYPTO_COINS)
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            prices = []
            for coin in CRYPTO_COINS:
                info = data.get(coin, {})
                prices.append({
                    "Coin": CRYPTO_NAMES[coin],
                    "Price": info.get("usd", 0),
                    "Change": round(info.get("usd_24h_change", 0), 2)
                })
            return prices
        except:
            return None

# ------------------------------------------------------------------
# TECHNICAL SIGNALS (simplified)
# ------------------------------------------------------------------
class TradingSignals:
    @staticmethod
    def generate_signals(df, pair):
        prices = df[pair].values
        if len(prices) < 35:
            return []
        rsi = np.random.uniform(20,80)  # dummy
        macd = np.random.uniform(-1,1)
        signals = []
        if rsi < 30:
            signals.append(("BUY", "RSI oversold"))
        elif rsi > 70:
            signals.append(("SELL", "RSI overbought"))
        if macd > 0.1:
            signals.append(("BUY", "MACD bullish"))
        return signals

# ------------------------------------------------------------------
# APP ROUTE (single page)
# ------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    username = request.args.get("user", "guest")
    mode = request.args.get("mode", "dashboard")
    use_real = request.args.get("real", "true") == "true"

    # Fetch data
    forex_df, forex_rates = ForexEngine.get_live_data(use_real)
    crypto_prices = CryptoEngine.fetch_prices()

    # Handle actions
    if request.method == "POST":
        action = request.form.get("action")
        if action == "login":
            user = request.form["username"]
            pwd = request.form["password"]
            if user in users_db and hashlib.sha256(pwd.encode()).hexdigest() == users_db[user]["password"]:
                username = user
        elif action == "trade":
            symbol = request.form["symbol"]
            trade_type = request.form["type"]
            amount = float(request.form["amount"])
            price = float(request.form["price"])
            leverage = float(request.form.get("leverage", 1))
            sl = request.form.get("sl")
            tp = request.form.get("tp")
            total = amount * price * leverage
            if get_balance(username) >= total:
                update_balance(username, -total)
                trades.append({
                    "id": len(trades)+1,
                    "username": username,
                    "symbol": symbol,
                    "type": trade_type,
                    "open_price": price,
                    "amount": amount,
                    "leverage": leverage,
                    "sl": float(sl) if sl else None,
                    "tp": float(tp) if tp else None,
                    "status": "open",
                    "timestamp": datetime.now().isoformat()
                })
        elif action == "close":
            trade_id = int(request.form["trade_id"])
            close_price = float(request.form["close_price"])
            for t in trades:
                if t["id"] == trade_id and t["status"] == "open":
                    if t["type"] == "buy":
                        pnl = (close_price - t["open_price"]) * t["amount"] * t["leverage"]
                    else:
                        pnl = (t["open_price"] - close_price) * t["amount"] * t["leverage"]
                    update_balance(username, pnl)
                    t["status"] = "closed"
                    t["pnl"] = pnl
                    t["close_price"] = close_price
                    break
        elif action == "alert":
            alerts_list.append({
                "username": username,
                "symbol": request.form["symbol"],
                "price": float(request.form["target"]),
                "direction": request.form["direction"]
            })

    # Prepare results for template
    balance = get_balance(username)
    open_positions = [t for t in trades if t["username"] == username and t["status"] == "open"]
    trade_history = [t for t in trades if t["username"] == username and t["status"] == "closed"]

    # Charts as JSON
    if mode == "dashboard" or mode == "forex":
        fig_forex = px.line(forex_df, x="Time", y=["EUR/USD", "GBP/USD"])
        chart_forex = fig_forex.to_json()
    else:
        chart_forex = None

    if mode == "crypto" and crypto_prices:
        fig_crypto = px.bar(pd.DataFrame(crypto_prices), x="Coin", y="Price", color="Change")
        chart_crypto = fig_crypto.to_json()
    else:
        chart_crypto = None

    # AI signals for Forex
    signals = []
    if mode == "ai":
        pair = request.args.get("pair", "EUR/USD")
        signals = TradingSignals.generate_signals(forex_df, pair)

    return render_template("index.html",
                           username=username,
                           mode=mode,
                           balance=balance,
                           forex_rates=forex_rates,
                           forex_df=forex_df,
                           crypto_prices=crypto_prices,
                           open_positions=open_positions,
                           trade_history=trade_history,
                           chart_forex=chart_forex,
                           chart_crypto=chart_crypto,
                           signals=signals,
                           pairs=ForexEngine.PAIRS,
                           coins=CRYPTO_COINS,
                           coin_names=CRYPTO_NAMES)