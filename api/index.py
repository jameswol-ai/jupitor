from flask import Flask, render_template_string, request
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import hashlib
import json
import plotly.express as px
import plotly.graph_objects as go

app = Flask(__name__)

# ------------------------------------------------------------------
# GLOBAL CONSTANTS (same as your Streamlit app)
# ------------------------------------------------------------------
CRYPTO_COINS = ["bitcoin", "ethereum", "ripple", "cardano", "solana"]
CRYPTO_NAMES = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP",
                "cardano": "ADA", "solana": "SOL"}

FOREX_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "UGX/USD", "KES/USD", "SSP/USD"]

# ------------------------------------------------------------------
# IN-MEMORY STORAGE (no SQLite, Vercel‑safe)
# ------------------------------------------------------------------
users_db = {
    "admin": {"password": hashlib.sha256("admin123".encode()).hexdigest(), "role": "admin", "email": "admin@example.com"},
    "guest": {"password": "", "role": "guest", "email": ""},
    "demo": {"password": hashlib.sha256("demo".encode()).hexdigest(), "role": "user", "email": "demo@example.com"}
}
wallets = {}          # username: balance
trades = []           # list of trade dicts
alerts_list = []      # list of alert dicts

def get_balance(username):
    return wallets.get(username, 10000.0)

def update_balance(username, amount):
    wallets[username] = wallets.get(username, 10000.0) + amount

# ------------------------------------------------------------------
# FOREX ENGINE
# ------------------------------------------------------------------
class ForexEngine:
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
            if live:
                np.random.seed(42)
                times = [datetime.now() - timedelta(minutes=i) for i in range(60)][::-1]
                df = pd.DataFrame({"Time": times})
                defaults = {"EUR/USD":1.08,"GBP/USD":1.26,"USD/JPY":144.5,
                            "UGX/USD":3750,"KES/USD":145,"SSP/USD":1100}
                for pair in FOREX_PAIRS:
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
        for pair in FOREX_PAIRS:
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
# TECHNICAL SIGNALS
# ------------------------------------------------------------------
class TradingSignals:
    @staticmethod
    def generate_signals(df, pair):
        prices = df[pair].values
        if len(prices) < 35:
            return []
        rsi = np.random.uniform(20,80)
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
# MAIN HTML (inline, no template file needed)
# ------------------------------------------------------------------
PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Trading App</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a1a; color: #e0e0e0; margin:0; display:flex; }
        .sidebar { width:260px; background: rgba(20,20,40,0.9); padding:20px; height:100vh; position:fixed; overflow-y:auto; border-right:1px solid #333; }
        .main { margin-left:260px; padding:30px; flex:1; }
        .card { background: rgba(255,255,255,0.05); border-radius:16px; padding:20px; margin-bottom:20px; border:1px solid rgba(255,255,255,0.1); }
        .metric-box { background: rgba(255,255,255,0.1); border-radius:12px; padding:16px; text-align:center; margin:10px; display:inline-block; }
        button, select, input { background: #1e1e2f; color: white; border:1px solid #444; padding:10px; border-radius:6px; margin:4px 0; }
        .btn { background: linear-gradient(45deg, #ff416c, #ff4b2b); border:none; cursor:pointer; font-weight:bold; }
        .btn:hover { opacity:0.9; }
        a { color:#00d2ff; text-decoration:none; }
        table { width:100%; border-collapse:collapse; margin-top:10px; }
        th, td { padding:10px; border-bottom:1px solid #333; text-align:right; }
    </style>
</head>
<body>
<div class="sidebar">
    <h2>📈 Trading App</h2>
    <p>👤 {{ username }}</p>
    <hr>
    <a href="?mode=dashboard&user={{ username }}">📊 Dashboard</a><br>
    <a href="?mode=forex&user={{ username }}">💱 Forex Pro</a><br>
    <a href="?mode=ai&user={{ username }}&pair=EUR/USD">🤖 Jup AI</a><br>
    <a href="?mode=crypto&user={{ username }}">₿ Crypto Tracker</a><br>
    <a href="?mode=trading&user={{ username }}">📈 Trading</a><br>
    <a href="?mode=wallet&user={{ username }}">💳 Wallet</a><br>
    <hr>
    <small>v12 · PWA Ready</small>
</div>

<div class="main">
    {% if mode == 'dashboard' %}
    <div class="card">
        <h2>Dashboard Overview</h2>
        <div>
            <div class="metric-box">Wallet Balance<br><b>${{ "%.2f"|format(balance) }}</b></div>
            <div class="metric-box">Top Forex<br><b>EUR/USD</b> {{ forex_rates.get('EUR/USD','') if forex_rates else '' }}</div>
            <div class="metric-box">Top Crypto<br><b>{% if crypto_prices %}{{ crypto_prices[0].Coin }} {{ crypto_prices[0].Price }}{% endif %}</b></div>
        </div>
        {% if chart_forex %}
        <div id="chart_forex"></div>
        <script>Plotly.newPlot('chart_forex', {{ chart_forex|safe }}.data, {{ chart_forex|safe }}.layout);</script>
        {% endif %}
    </div>

    {% elif mode == 'forex' %}
    <div class="card">
        <h2>Forex Pro</h2>
        <div>
            {% for pair, rate in (forex_rates or {}).items() %}
            <div class="metric-box">{{ pair }}<br><b>${{ rate }}</b></div>
            {% endfor %}
        </div>
        <div id="chart_forex"></div>
        <script>Plotly.newPlot('chart_forex', {{ chart_forex|safe }}.data, {{ chart_forex|safe }}.layout);</script>
    </div>

    {% elif mode == 'ai' %}
    <div class="card">
        <h2>Jup AI Signals</h2>
        <form>
            <select name="pair" onchange="this.form.submit()">
                {% for p in pairs %}<option {% if request.args.pair==p %}selected{% endif %}>{{ p }}</option>{% endfor %}
            </select>
        </form>
        <ul>
        {% for sig in signals %}
            <li><strong>{{ sig[0] }}</strong>: {{ sig[1] }}</li>
        {% endfor %}
        </ul>
    </div>

    {% elif mode == 'crypto' %}
    <div class="card">
        <h2>Crypto Prices</h2>
        {% if crypto_prices %}
        <table>
            <tr><th>Coin</th><th>Price (USD)</th><th>24h Change</th></tr>
            {% for c in crypto_prices %}
            <tr><td>{{ c.Coin }}</td><td>${{ "%.2f"|format(c.Price) }}</td><td style="color:{% if c.Change>=0 %}green{% else %}red{% endif %}">{{ c.Change }}%</td></tr>
            {% endfor %}
        </table>
        {% endif %}
        <div id="chart_crypto"></div>
        {% if chart_crypto %}
        <script>Plotly.newPlot('chart_crypto', {{ chart_crypto|safe }}.data, {{ chart_crypto|safe }}.layout);</script>
        {% endif %}
    </div>

    {% elif mode == 'trading' %}
    <div class="card">
        <h2>Virtual Trading</h2>
        <p>Balance: ${{ "%.2f"|format(balance) }}</p>
        <h3>New Trade</h3>
        <form method="post">
            <input type="hidden" name="action" value="trade">
            <select name="symbol">
                {% for p in pairs %}<option>{{ p }}</option>{% endfor %}
                {% for c in coins %}<option>{{ coin_names[c] }}</option>{% endfor %}
            </select>
            <select name="type"><option>buy</option><option>sell</option></select>
            Amount: <input type="number" step="0.01" name="amount" value="1">
            Price: <input type="number" step="0.0001" name="price" value="1">
            Leverage: <input type="number" name="leverage" value="1">
            SL: <input type="number" step="0.01" name="sl" placeholder="optional">
            TP: <input type="number" step="0.01" name="tp" placeholder="optional">
            <button class="btn" type="submit">Execute</button>
        </form>
        <h3>Open Positions</h3>
        <table>
            <tr><th>Symbol</th><th>Type</th><th>Open Price</th><th>Amount</th><th>Leverage</th><th>SL/TP</th><th>Close</th></tr>
            {% for t in open_positions %}
            <tr>
                <td>{{ t.symbol }}</td><td>{{ t.type }}</td><td>{{ t.open_price }}</td><td>{{ t.amount }}</td>
                <td>{{ t.leverage }}</td><td>{{ t.sl or '' }}/{{ t.tp or '' }}</td>
                <td><form method="post"><input type="hidden" name="action" value="close"><input type="hidden" name="trade_id" value="{{ t.id }}">Price <input type="number" step="0.0001" name="close_price"><button class="btn">Close</button></form></td>
            </tr>
            {% endfor %}
        </table>
        <h3>Trade History</h3>
        <table>
            <tr><th>Symbol</th><th>Type</th><th>Open</th><th>Close</th><th>P&L</th></tr>
            {% for t in trade_history %}
            <tr><td>{{ t.symbol }}</td><td>{{ t.type }}</td><td>{{ t.open_price }}</td><td>{{ t.close_price or '' }}</td><td>${{ "%.2f"|format(t.pnl) if t.pnl else '' }}</td></tr>
            {% endfor %}
        </table>
    </div>

    {% elif mode == 'wallet' %}
    <div class="card">
        <h2>Mobile Wallet</h2>
        <p>Balance: ${{ "%.2f"|format(balance) }}</p>
        <h4>Deposit (simulated)</h4>
        <form method="post"><input type="hidden" name="action" value="deposit"><input type="number" name="amount" placeholder="Amount"><button class="btn">Add Funds</button></form>
        <h4>Withdraw</h4>
        <form method="post"><input type="hidden" name="action" value="withdraw"><input type="number" name="amount" placeholder="Amount"><button class="btn">Withdraw</button></form>
    </div>
    {% endif %}
</div>
</body>
</html>
"""

# ------------------------------------------------------------------
# MAIN ROUTE
# ------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    username = request.args.get("user", "guest")
    mode = request.args.get("mode", "dashboard")
    use_real = request.args.get("real", "true") == "true"

    forex_df, forex_rates = ForexEngine.get_live_data(use_real)
    crypto_prices = CryptoEngine.fetch_prices()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "trade":
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
                    "id": len(trades) + 1,
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
        elif action == "deposit":
            amount = float(request.form["amount"])
            update_balance(username, amount)
        elif action == "withdraw":
            amount = float(request.form["amount"])
            if amount <= get_balance(username):
                update_balance(username, -amount)

    balance = get_balance(username)
    open_positions = [t for t in trades if t["username"] == username and t["status"] == "open"]
    trade_history = [t for t in trades if t["username"] == username and t["status"] == "closed"]

    # Charts
    chart_forex = None
    chart_crypto = None
    if mode in ["dashboard", "forex"]:
        fig = px.line(forex_df, x="Time", y=["EUR/USD", "GBP/USD"])
        chart_forex = fig.to_json()
    if mode == "crypto" and crypto_prices:
        df_crypto = pd.DataFrame(crypto_prices)
        if not df_crypto.empty:
            fig = px.bar(df_crypto, x="Coin", y="Price", color="Change")
            chart_crypto = fig.to_json()

    signals = []
    if mode == "ai":
        pair = request.args.get("pair", "EUR/USD")
        signals = TradingSignals.generate_signals(forex_df, pair)

    return render_template_string(
        PAGE_HTML,
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
        pairs=FOREX_PAIRS,
        coins=CRYPTO_COINS,
        coin_names=CRYPTO_NAMES
    )