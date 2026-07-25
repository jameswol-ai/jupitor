import streamlit as st
import pandas as pd
import numpy as np
import requests
import sqlite3
from datetime import datetime, timedelta
import hashlib
import json
import smtplib
from email.message import EmailMessage
import base64

# Optional imports – app works without them
try:
    from streamlit_autorefresh import st_autorefresh
    AUTO_REFRESH = True
except ImportError:
    AUTO_REFRESH = False

try:
    import feedparser
    RSS_AVAILABLE = True
except ImportError:
    RSS_AVAILABLE = False

# ------------------------------------------------------------------
# PAGE CONFIG (must be first)
# ------------------------------------------------------------------
st.set_page_config(page_title="Trading App", page_icon="📈", layout="wide")

# ------------------------------------------------------------------
# VERCEL SPEED INSIGHTS (optional)
# ------------------------------------------------------------------
st.components.v1.html("""
    <script>
        (function() {
            var script = document.createElement('script');
            script.defer = true;
            script.src = '/_vercel/speed-insights/script.js';
            document.head.appendChild(script);
        })();
    </script>
""", height=0)

if AUTO_REFRESH:
    st_autorefresh(interval=30000, key="datarefresh")

# ------------------------------------------------------------------
# GLOBAL CONSTANTS
# ------------------------------------------------------------------
CRYPTO_COINS = ["bitcoin", "ethereum", "ripple", "cardano", "solana"]
CRYPTO_NAMES = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP",
                "cardano": "ADA", "solana": "SOL"}

# ------------------------------------------------------------------
# DATABASE SETUP
# ------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect("trading_app.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT DEFAULT 'user')''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass
    # Default admin account
    c.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
    if c.fetchone()[0] == 0:
        admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute("INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, 'admin')",
                  ("admin", admin_hash, "admin@example.com"))
    else:
        c.execute("UPDATE users SET email='admin@example.com' WHERE username='admin' AND email IS NULL")
    c.execute('''CREATE TABLE IF NOT EXISTS forex_quotes
                 (timestamp TEXT, pair TEXT, rate REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wallet_transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT, type TEXT, amount REAL,
                  phone TEXT, provider TEXT, reference TEXT,
                  status TEXT, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  symbol TEXT,
                  trade_type TEXT,
                  open_price REAL,
                  amount REAL,
                  leverage REAL DEFAULT 1,
                  stop_loss REAL,
                  take_profit REAL,
                  timestamp TEXT,
                  status TEXT DEFAULT 'open',
                  close_price REAL,
                  close_timestamp TEXT,
                  pnl REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS alerts
                 (username TEXT,
                  symbol TEXT,
                  price REAL,
                  direction TEXT)''')
    conn.commit()
    return conn

def get_db_connection():
    return sqlite3.connect("trading_app.db")

init_db()

# ------------------------------------------------------------------
# AUTHENTICATION & 2FA
# ------------------------------------------------------------------
def authenticate(username, password):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT password_hash, role FROM users WHERE username=?", (username,))
    row = c.fetchone()
    if row:
        db_hash, role = row
        if hashlib.sha256(password.encode()).hexdigest() == db_hash:
            return True, role
    # Fallback demo (for development only – move to secrets in production)
    if username == "demo" and hashlib.sha256("demo".encode()).hexdigest() == hashlib.sha256(password.encode()).hexdigest():
        return True, "user"
    return False, None

def send_otp(email):
    otp = str(np.random.randint(100000, 999999))
    st.session_state.otp = otp
    send_email_notification(email, "Your OTP", f"Your one‑time password is: {otp}")
    return otp

def add_user(username, password, email, role="user"):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute("INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
                  (username, pwd_hash, email, role))
        conn.commit()
        send_email_notification(email, "Account Created", f"Hello {username}, your account has been created.")
        return True, f"User '{username}' added."
    except sqlite3.IntegrityError:
        return False, "Username already exists."

def update_user_email(username, new_email):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET email=? WHERE username=?", (new_email, username))
    conn.commit()
    return True

def delete_user(username):
    if username == "admin":
        return False, "Cannot delete admin account."
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    return True, f"User '{username}' deleted."

def get_all_users():
    conn = get_db_connection()
    return pd.read_sql_query("SELECT username, role, email FROM users", conn)

# ------------------------------------------------------------------
# EMAIL
# ------------------------------------------------------------------
def send_email_notification(to_email, subject, body):
    try:
        sender = st.secrets["email_sender"]
        password = st.secrets["email_password"]
        smtp_server = st.secrets.get("smtp_server", "smtp.gmail.com")
        smtp_port = st.secrets.get("smtp_port", 587)
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.warning(f"Email could not be sent: {e}")
        return False

# ------------------------------------------------------------------
# TOAST FALLBACK
# ------------------------------------------------------------------
def show_toast(message, type="info"):
    try:
        st.toast(message)
    except AttributeError:
        if type == "info":
            st.info(message)
        elif type == "success":
            st.success(message)
        elif type == "warning":
            st.warning(message)
        elif type == "error":
            st.error(message)

# ------------------------------------------------------------------
# MOBILE WALLET
# ------------------------------------------------------------------
class MobileWallet:
    PROVIDERS = ["M-Pesa (Kenya)", "Airtel Money (Uganda)", "MTN MoMo (Uganda)"]

    @staticmethod
    def get_balance(username):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""SELECT SUM(CASE WHEN type='deposit' THEN amount
                                     WHEN type='withdrawal' THEN -amount
                                     WHEN type='trade' THEN amount
                                     ELSE 0 END)
                     FROM wallet_transactions
                     WHERE username=? AND status='completed'""", (username,))
        row = c.fetchone()
        return row[0] if row[0] is not None else 0.0

    @staticmethod
    def deposit_request(username, phone, amount, provider):
        ref = f"DEP{datetime.now().strftime('%Y%m%d%H%M%S')}"
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO wallet_transactions
                     (username, type, amount, phone, provider, reference, status, timestamp)
                     VALUES (?, 'deposit', ?, ?, ?, ?, 'pending', ?)''',
                  (username, amount, phone, provider, ref, datetime.now().isoformat()))
        conn.commit()
        return ref

    @staticmethod
    def confirm_deposit(reference):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE wallet_transactions SET status='completed' WHERE reference=?", (reference,))
        conn.commit()
        return True

    @staticmethod
    def withdraw_request(username, phone, amount, provider):
        balance = MobileWallet.get_balance(username)
        if amount > balance:
            return None, "Insufficient balance."
        ref = f"WTH{datetime.now().strftime('%Y%m%d%H%M%S')}"
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO wallet_transactions
                     (username, type, amount, phone, provider, reference, status, timestamp)
                     VALUES (?, 'withdrawal', ?, ?, ?, ?, 'pending', ?)''',
                  (username, amount, phone, provider, ref, datetime.now().isoformat()))
        conn.commit()
        return ref, "Withdrawal request submitted."

    @staticmethod
    def confirm_withdrawal(reference):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE wallet_transactions SET status='completed' WHERE reference=?", (reference,))
        conn.commit()
        return True

    @staticmethod
    def get_transactions(username, limit=20):
        conn = get_db_connection()
        return pd.read_sql_query(
            "SELECT * FROM wallet_transactions WHERE username=? ORDER BY timestamp DESC LIMIT ?",
            conn, params=(username, limit))

# ------------------------------------------------------------------
# FOREX ENGINE
# ------------------------------------------------------------------
class ForexEngine:
    PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "UGX/USD", "KES/USD", "SSP/USD"]

    @staticmethod
    def fetch_latest_rates():
        live_rates = {}
        try:
            resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
            resp.raise_for_status()
            data = resp.json()["rates"]
            usd_to = data
            pair_map = {
                "EUR/USD": "EUR", "GBP/USD": "GBP", "USD/JPY": "JPY",
                "UGX/USD": "UGX", "KES/USD": "KES", "SSP/USD": "SSP"
            }
            for pair, code in pair_map.items():
                if code in usd_to:
                    if pair in ["EUR/USD", "GBP/USD"]:
                        live_rates[pair] = round(1 / usd_to[code], 4)
                    else:
                        live_rates[pair] = round(usd_to[code], 4)
            return live_rates
        except:
            return None

    @staticmethod
    def get_live_data(minutes=60, use_real=True, store_db=True):
        if use_real:
            live = ForexEngine.fetch_latest_rates()
            if live is not None:
                np.random.seed(42)
                now = datetime.now()
                times = [now - timedelta(minutes=i) for i in range(minutes)][::-1]
                data = {"Time": times}
                defaults = {"EUR/USD":1.08,"GBP/USD":1.26,"USD/JPY":144.5,
                            "UGX/USD":3750,"KES/USD":145,"SSP/USD":1100}
                for pair in ForexEngine.PAIRS:
                    base = live.get(pair, defaults.get(pair, 1.0))
                    vol = base * 0.0002
                    prices = base + np.cumsum(np.random.normal(0, vol, minutes))
                    data[pair] = np.round(np.maximum(prices, 0.0001), 4)
                df = pd.DataFrame(data)
                if store_db:
                    ForexEngine._store_quotes(live)
                return df
        return ForexEngine._simulated_data(minutes)

    @staticmethod
    def _simulated_data(minutes=60):
        np.random.seed(42)
        now = datetime.now()
        times = [now - timedelta(minutes=i) for i in range(minutes)][::-1]
        base = {"EUR/USD": 1.08, "GBP/USD": 1.26, "USD/JPY": 144.5,
                "UGX/USD": 3750, "KES/USD": 145, "SSP/USD": 1100}
        vol = {"EUR/USD": 0.0003, "GBP/USD": 0.0004, "USD/JPY": 0.02,
               "UGX/USD": 2, "KES/USD": 0.1, "SSP/USD": 5}
        data = {"Time": times}
        for pair in ForexEngine.PAIRS:
            data[pair] = np.round(base[pair] + np.cumsum(np.random.normal(0, vol[pair], minutes)), 4)
        return pd.DataFrame(data)

    @staticmethod
    def _store_quotes(rates):
        conn = get_db_connection()
        c = conn.cursor()
        ts = datetime.now().isoformat()
        for pair, rate in rates.items():
            if rate is not None:
                c.execute("INSERT INTO forex_quotes VALUES (?, ?, ?)", (ts, pair, rate))
        conn.commit()

    @staticmethod
    def get_history(pair, limit=100):
        conn = get_db_connection()
        df = pd.read_sql_query(
            "SELECT timestamp, rate FROM forex_quotes WHERE pair=? ORDER BY timestamp DESC LIMIT ?",
            conn, params=(pair, limit))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.iloc[::-1]

    @staticmethod
    def get_summary(df):
        latest = df.iloc[-1]
        prev = df.iloc[0] if len(df) > 1 else latest
        summary = []
        for pair in ForexEngine.PAIRS:
            cur = latest[pair]
            change = cur - prev[pair]
            pct = (change / prev[pair]) * 100 if prev[pair] != 0 else 0
            summary.append({"Pair": pair, "Last": round(cur, 4),
                            "Change": round(change, 4), "Change %": f"{pct:.2f}%"})
        return pd.DataFrame(summary)

    @staticmethod
    def get_correlation_matrix(df):
        returns = df[ForexEngine.PAIRS].pct_change().dropna()
        return returns.corr().round(2)

    @staticmethod
    def get_volume(minutes=60):
        np.random.seed(99)
        now = datetime.now()
        times = [now - timedelta(minutes=i) for i in range(minutes)][::-1]
        volume = np.random.randint(500, 5000, minutes)
        return pd.DataFrame({"Time": times, "Volume": volume})

# ------------------------------------------------------------------
# TECHNICAL INDICATORS
# ------------------------------------------------------------------
class TradingSignals:
    @staticmethod
    def compute_rsi(prices, period=14):
        deltas = np.diff(prices)
        if len(deltas) < period:
            return np.full_like(prices, np.nan)
        up = np.mean(np.maximum(deltas[:period], 0))
        down = np.mean(np.abs(np.minimum(deltas[:period], 0)))
        rsi = np.zeros_like(prices)
        if down == 0:
            rsi[:period+1] = 100.0
        else:
            rs = up / down
            rsi[:period+1] = 100.0 - 100.0 / (1.0 + rs)
        for i in range(period, len(deltas)):
            delta = deltas[i]
            up = (up * (period-1) + max(delta, 0)) / period
            down = (down * (period-1) + abs(min(delta, 0))) / period
            if down == 0:
                rsi[i+1] = 100.0
            else:
                rs = up / down
                rsi[i+1] = 100.0 - 100.0 / (1.0 + rs)
        return rsi

    @staticmethod
    def compute_macd(prices, fast=12, slow=26, signal=9):
        ema_fast = pd.Series(prices).ewm(span=fast, adjust=False).mean()
        ema_slow = pd.Series(prices).ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line.values, signal_line.values, histogram.values

    @staticmethod
    def bollinger_bands(prices, window=20, num_std=2):
        rolling_mean = pd.Series(prices).rolling(window).mean()
        rolling_std = pd.Series(prices).rolling(window).std()
        upper_band = rolling_mean + (rolling_std * num_std)
        lower_band = rolling_mean - (rolling_std * num_std)
        return rolling_mean.values, upper_band.values, lower_band.values

    @staticmethod
    def generate_signals(df, pair):
        prices = df[pair].values
        if len(prices) < 35:
            return []
        rsi = TradingSignals.compute_rsi(prices)
        macd, signal, hist = TradingSignals.compute_macd(prices)
        bb_mid, bb_up, bb_low = TradingSignals.bollinger_bands(prices)
        signals = []
        last_rsi = rsi[-1]
        last_macd = macd[-1]
        last_signal = signal[-1]
        prev_macd = macd[-2]
        prev_signal = signal[-2]
        if last_rsi < 30:
            signals.append(("BUY", "RSI oversold"))
        elif last_rsi > 70:
            signals.append(("SELL", "RSI overbought"))
        if prev_macd < prev_signal and last_macd > last_signal:
            signals.append(("BUY", "MACD bullish crossover"))
        elif prev_macd > prev_signal and last_macd < last_signal:
            signals.append(("SELL", "MACD bearish crossover"))
        if prices[-1] < bb_low[-1]:
            signals.append(("BUY", "Price below lower Bollinger Band"))
        elif prices[-1] > bb_up[-1]:
            signals.append(("SELL", "Price above upper Bollinger Band"))
        return signals

# ------------------------------------------------------------------
# FORECAST
# ------------------------------------------------------------------
def weighted_linear_fit(x, y, tau=7):
    n = len(x)
    weights = np.exp(-np.arange(n)[::-1] / tau)
    W = np.diag(weights)
    X = np.column_stack([np.ones_like(x), x])
    XtW = X.T @ W
    coeffs = np.linalg.solve(XtW @ X, XtW @ (W @ y))
    return coeffs

class ForexForecast:
    BASE_PRICES = {
        "EUR/USD": 1.08, "GBP/USD": 1.26, "USD/JPY": 144.5,
        "UGX/USD": 3750, "KES/USD": 145, "SSP/USD": 1100
    }
    DAILY_VOL = {
        "EUR/USD": 0.005, "GBP/USD": 0.006, "USD/JPY": 0.25,
        "UGX/USD": 15, "KES/USD": 0.8, "SSP/USD": 12
    }

    @staticmethod
    def generate_daily_history(days=90):
        np.random.seed(123)
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        df = pd.DataFrame(index=dates)
        for pair in ForexEngine.PAIRS:
            start = ForexForecast.BASE_PRICES[pair]
            vol = ForexForecast.DAILY_VOL[pair] * start
            drift = 0.0001 * start if pair in ["EUR/USD","GBP/USD"] else 0.01
            rets = np.random.normal(drift, vol, days)
            prices = start * np.exp(np.cumsum(rets / start))
            df[pair] = np.round(prices, 4)
        return df

    @staticmethod
    def forecast(df, horizon_days, pair):
        series = df[pair].tail(30)
        x = np.arange(len(series))
        y = series.values
        coeffs = weighted_linear_fit(x, y, tau=7)
        last_idx = len(series) - 1
        future_x = np.array([last_idx + d for d in range(1, horizon_days+1)])
        return np.round(coeffs[0] + coeffs[1] * future_x, 4)

class CryptoForecast:
    BASE_PRICES = {"bitcoin": 67000, "ethereum": 3400, "ripple": 0.6, "cardano": 0.45, "solana": 170}
    DAILY_VOL = {"bitcoin": 1500, "ethereum": 120, "ripple": 0.03, "cardano": 0.02, "solana": 8}

    @staticmethod
    def generate_daily_history(days=90, live_prices=None):
        np.random.seed(456)
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        df = pd.DataFrame(index=dates)
        for coin in CRYPTO_COINS:
            start = CryptoForecast.BASE_PRICES[coin]
            vol = CryptoForecast.DAILY_VOL[coin]
            drift = 0.0005 * start
            rets = np.random.normal(drift, vol, days)
            prices = start + np.cumsum(rets)
            prices = np.maximum(prices, 0.01)
            if live_prices and coin in live_prices and live_prices[coin] is not None:
                prices[-1] = live_prices[coin]
            df[coin] = np.round(prices, 2)
        return df

    @staticmethod
    def forecast(df, horizon_days, coin):
        series = df[coin].tail(30)
        x = np.arange(len(series))
        y = series.values
        coeffs = weighted_linear_fit(x, y, tau=7)
        last_idx = len(series) - 1
        future_x = np.array([last_idx + d for d in range(1, horizon_days+1)])
        return np.round(coeffs[0] + coeffs[1] * future_x, 2)

# ------------------------------------------------------------------
# CRYPTO ENGINE
# ------------------------------------------------------------------
class CryptoEngine:
    @staticmethod
    def fetch_prices():
        try:
            ids = ",".join(CRYPTO_COINS)
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            prices = []
            for coin in CRYPTO_COINS:
                info = data.get(coin, {})
                prices.append({
                    "Coin": CRYPTO_NAMES[coin],
                    "Price (USD)": info.get("usd"),
                    "24h Change %": round(info.get("usd_24h_change", 0), 2)
                })
            return pd.DataFrame(prices)
        except Exception as e:
            st.warning(f"Crypto fetch failed: {e}")
            return None

    @staticmethod
    def get_historical(coin_id, days=7):
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            prices = data["prices"]
            df = pd.DataFrame(prices, columns=["timestamp", "price"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df.set_index("timestamp")
        except:
            return None

# ------------------------------------------------------------------
# TRADING MODULE (with Stop‑Loss / Take‑Profit)
# ------------------------------------------------------------------
class TradingModule:
    @staticmethod
    def open_trade(username, symbol, trade_type, amount, open_price, leverage=1,
                   stop_loss=None, take_profit=None):
        conn = get_db_connection()
        c = conn.cursor()
        ts = datetime.now().isoformat()
        c.execute('''INSERT INTO trades (username, symbol, trade_type, open_price, amount, leverage,
                     stop_loss, take_profit, timestamp, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')''',
                  (username, symbol, trade_type, open_price, amount, leverage,
                   stop_loss, take_profit, ts))
        conn.commit()
        return True

    @staticmethod
    def get_open_positions(username):
        conn = get_db_connection()
        return pd.read_sql_query("SELECT * FROM trades WHERE username=? AND status='open'", conn, params=(username,))

    @staticmethod
    def close_trade(trade_id, close_price):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM trades WHERE id=?", (trade_id,))
        trade = c.fetchone()
        if not trade:
            return False, "Trade not found."
        id, username, symbol, trade_type, open_price, amount, leverage, sl, tp, ts, status, cp, cts, pnl = trade
        if status != 'open':
            return False, "Trade already closed."
        if trade_type == 'buy':
            pnl_val = (close_price - open_price) * amount * leverage
        else:
            pnl_val = (open_price - close_price) * amount * leverage
        close_ts = datetime.now().isoformat()
        c.execute("UPDATE trades SET status='closed', close_price=?, close_timestamp=?, pnl=? WHERE id=?",
                  (close_price, close_ts, round(pnl_val, 4), trade_id))
        ref = f"TRD{trade_id}{close_ts}"
        c.execute('''INSERT INTO wallet_transactions (username, type, amount, phone, provider, reference, status, timestamp)
                     VALUES (?, 'trade', ?, 'system', 'Trading', ?, 'completed', ?)''',
                  (username, round(pnl_val, 4), ref, close_ts))
        conn.commit()
        return True, f"Trade closed. P&L: ${pnl_val:.2f}"

    @staticmethod
    def check_stop_loss_take_profit(username):
        positions = TradingModule.get_open_positions(username)
        if positions.empty:
            return
        for _, pos in positions.iterrows():
            if pos['symbol'] in ForexEngine.PAIRS:
                if 'forex_data' not in st.session_state:
                    continue
                current_price = st.session_state.forex_data.iloc[-1][pos['symbol']]
            else:
                if st.session_state.get('crypto_live_prices') is None:
                    continue
                row = st.session_state.crypto_live_prices[st.session_state.crypto_live_prices['Coin'] == CRYPTO_NAMES.get(pos['symbol'], '')]
                if row.empty:
                    continue
                current_price = row.iloc[0]['Price (USD)']
            sl = pos['stop_loss']
            tp = pos['take_profit']
            if sl is not None and sl > 0:
                if (pos['trade_type'] == 'buy' and current_price <= sl) or \
                   (pos['trade_type'] == 'sell' and current_price >= sl):
                    TradingModule.close_trade(pos['id'], current_price)
                    show_toast(f"Stop‑loss triggered for {pos['symbol']} at {current_price}", type="warning")
            if tp is not None and tp > 0:
                if (pos['trade_type'] == 'buy' and current_price >= tp) or \
                   (pos['trade_type'] == 'sell' and current_price <= tp):
                    TradingModule.close_trade(pos['id'], current_price)
                    show_toast(f"Take‑profit triggered for {pos['symbol']} at {current_price}", type="success")

    @staticmethod
    def get_trade_history(username, limit=30):
        conn = get_db_connection()
        return pd.read_sql_query("SELECT * FROM trades WHERE username=? ORDER BY timestamp DESC LIMIT ?",
                                 conn, params=(username, limit))

# ------------------------------------------------------------------
# PRICE ALERTS
# ------------------------------------------------------------------
def check_price_alerts(username):
    conn = get_db_connection()
    alerts = pd.read_sql_query("SELECT * FROM alerts WHERE username=?", conn, params=(username,))
    for _, alert in alerts.iterrows():
        symbol = alert['symbol']
        price_target = alert['price']
        direction = alert['direction']
        if symbol in ForexEngine.PAIRS:
            current = st.session_state.forex_data.iloc[-1][symbol]
        else:
            live = st.session_state.crypto_live_prices
            if live is not None:
                row = live[live['Coin'] == CRYPTO_NAMES.get(symbol, '')]
                current = row.iloc[0]['Price (USD)'] if not row.empty else None
            else:
                continue
        if current is not None:
            if direction == 'above' and current >= price_target:
                show_toast(f"🚨 {symbol} is now above {price_target}!")
                c = conn.cursor()
                c.execute("DELETE FROM alerts WHERE username=? AND symbol=? AND price=? AND direction=?",
                          (username, symbol, price_target, direction))
                conn.commit()
            elif direction == 'below' and current <= price_target:
                show_toast(f"🚨 {symbol} is now below {price_target}!")
                c = conn.cursor()
                c.execute("DELETE FROM alerts WHERE username=? AND symbol=? AND price=? AND direction=?",
                          (username, symbol, price_target, direction))
                conn.commit()

# ------------------------------------------------------------------
# BACKTESTING
# ------------------------------------------------------------------
def backtest_rsi_strategy(prices, rsi_period=14, oversold=30, overbought=70):
    rsi = TradingSignals.compute_rsi(prices, rsi_period)
    capital = 10000
    position = 0
    equity = [capital]
    for i in range(rsi_period, len(prices)-1):
        if rsi[i] < oversold and position == 0:
            position = capital / prices[i]
            capital = 0
        elif rsi[i] > overbought and position > 0:
            capital = position * prices[i]
            position = 0
        equity.append(capital + position * prices[i])
    return equity

# ------------------------------------------------------------------
# SENTIMENT
# ------------------------------------------------------------------
def fetch_market_sentiment():
    if not RSS_AVAILABLE:
        return np.random.randint(-3, 4)
    sentiment_score = 0
    try:
        feed = feedparser.parse("https://www.investing.com/rss/news_25.rss")
        for entry in feed.entries[:5]:
            if "bull" in entry.title.lower() or "gain" in entry.title.lower():
                sentiment_score += 1
            elif "bear" in entry.title.lower() or "drop" in entry.title.lower():
                sentiment_score -= 1
    except:
        sentiment_score = np.random.randint(-3, 4)
    return sentiment_score

# ------------------------------------------------------------------
# SIDEBAR AUTHENTICATION (NEW)
# ------------------------------------------------------------------
def show_logo():
    st.markdown("""
    <div style="display:flex; justify-content:center;">
        <svg width="90" height="90" viewBox="0 0 100 100">
            <defs>
                <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" style="stop-color:#00d2ff;stop-opacity:1" />
                    <stop offset="100%" style="stop-color:#3a7bd5;stop-opacity:1" />
                </linearGradient>
            </defs>
            <path d="M15,80 A60,60 0 0,1 85,80" stroke="url(#grad)" stroke-width="5" fill="none" stroke-linecap="round"/>
            <circle cx="50" cy="68" r="6" fill="#ff4b2b" filter="drop-shadow(0 0 6px #ff4b2b)"/>
        </svg>
    </div>
    """, unsafe_allow_html=True)

def render_sidebar_auth():
    """Show login or registration forms inside the sidebar."""
    st.sidebar.title("🔐 Account")
    auth_option = st.sidebar.radio("Select", ["Login", "Create Account"], horizontal=True)

    if auth_option == "Login":
        with st.sidebar.form("login_form_sidebar"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            use_2fa = st.checkbox("Enable 2‑Factor Authentication (OTP)")
            otp_input = None
            if use_2fa:
                otp_input = st.text_input("OTP (sent to your email)")
            submitted = st.form_submit_button("🔓 Login")
            if submitted:
                success, role = authenticate(username, password)
                if success:
                    if use_2fa:
                        if 'otp' not in st.session_state or otp_input != st.session_state.otp:
                            st.sidebar.error("Invalid OTP. Request a new one if needed.")
                            st.stop()
                    st.session_state.authenticated = True
                    st.session_state.username = username
                    st.session_state.role = role
                    st.rerun()
                else:
                    st.sidebar.error("Invalid username or password.")
        # OTP request outside the form
        if use_2fa and username:
            if st.sidebar.button("📧 Send OTP"):
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT email FROM users WHERE username=?", (username,))
                row = c.fetchone()
                if row and row[0]:
                    send_otp(row[0])
                    st.sidebar.success("OTP sent to your email.")
                else:
                    st.sidebar.warning("User email not found.")
    else:  # Create Account
        with st.sidebar.form("register_form_sidebar"):
            new_username = st.text_input("Choose Username")
            new_password = st.text_input("Choose Password", type="password")
            new_email = st.text_input("Email")
            submitted = st.form_submit_button("🆕 Register")
            if submitted:
                if not new_username or not new_password or not new_email:
                    st.sidebar.error("All fields are required.")
                else:
                    success, msg = add_user(new_username, new_password, new_email)
                    if success:
                        st.sidebar.success(msg + " You can now login.")
                    else:
                        st.sidebar.error(msg)

# ------------------------------------------------------------------
# SESSION STATE & LOGIN
# ------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    # ---- Sidebar auth ----
    render_sidebar_auth()
    # ---- Main area shows a welcome screen ----
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        show_logo()
        st.markdown("<h1 style='text-align:center;'>📈 Trading App</h1>", unsafe_allow_html=True)
        st.markdown("Welcome to the advanced trading dashboard. Please log in via the sidebar to access forex, crypto, and wallet features.")
    st.stop()

# ------------------------------------------------------------------
# REST OF THE APP (AFTER LOGIN)
# ------------------------------------------------------------------
def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# Sidebar after authentication
with st.sidebar:
    show_logo()
    st.write(f"👤 {st.session_state.username} ({st.session_state.role})")
    mode_options = ["📊 Dashboard", "💱 Forex Pro", "🤖 Jup AI", "₿ Crypto Tracker", "📈 Trading", "💳 Mobile Wallet"]
    if 'mode' not in st.session_state:
        st.session_state.mode = mode_options[0]
    mode = st.radio("🧠 Engine", mode_options, index=mode_options.index(st.session_state.mode))
    st.session_state.mode = mode
    if mode == "💱 Forex Pro":
        st.checkbox("Real‑time forex", value=st.session_state.use_real_forex, key="use_real_forex")
    with st.expander("⚙️ Account Settings"):
        new_email = st.text_input("New email", value="")
        if st.button("Update Email"):
            if new_email:
                update_user_email(st.session_state.username, new_email)
                st.success("Email updated.")
    if st.session_state.role == "admin":
        with st.expander("👥 User Management"):
            st.subheader("Add User")
            with st.form("admin_add_user"):
                new_user = st.text_input("Username")
                new_pass = st.text_input("Password", type="password")
                new_email = st.text_input("Email")
                new_role = st.selectbox("Role", ["user", "admin"])
                if st.form_submit_button("Add User"):
                    if new_user and new_pass and new_email:
                        success, msg = add_user(new_user, new_pass, new_email, new_role)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
                    else:
                        st.error("All fields required.")
            st.subheader("Existing Users")
            users_df = get_all_users()
            for idx, row in users_df.iterrows():
                col1, col2, col3 = st.columns([3,2,1])
                with col1:
                    st.write(f"**{row['username']}** ({row['role']})")
                with col2:
                    st.write(row['email'])
                with col3:
                    if row['username'] != 'admin':
                        if st.button("🗑️", key=f"del_{row['username']}"):
                            d_success, d_msg = delete_user(row['username'])
                            if d_success:
                                st.success(d_msg)
                            else:
                                st.error(d_msg)
                            st.rerun()
    if st.button("🚪 Logout"):
        logout()
    st.caption("v12 · PWA Ready")

# ------------------------------------------------------------------
# DATA INIT (after login)
# ------------------------------------------------------------------
if 'role' not in st.session_state:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE username=?", (st.session_state.username,))
    row = c.fetchone()
    st.session_state.role = row[0] if row else "user"

if 'forex_data' not in st.session_state:
    st.session_state.forex_data = ForexEngine.get_live_data(use_real=True)
if 'forex_volume' not in st.session_state:
    st.session_state.forex_volume = ForexEngine.get_volume()
if 'use_real_forex' not in st.session_state:
    st.session_state.use_real_forex = True
if 'forex_daily_hist' not in st.session_state:
    st.session_state.forex_daily_hist = ForexForecast.generate_daily_history(90)
if 'crypto_live_prices' not in st.session_state:
    st.session_state.crypto_live_prices = CryptoEngine.fetch_prices()
if 'crypto_daily_hist' not in st.session_state:
    live_dict = {}
    if st.session_state.crypto_live_prices is not None:
        for _, row in st.session_state.crypto_live_prices.iterrows():
            for cid, name in CRYPTO_NAMES.items():
                if name == row["Coin"]:
                    live_dict[cid] = row["Price (USD)"]
    st.session_state.crypto_daily_hist = CryptoForecast.generate_daily_history(90, live_dict)

# Check stop‑loss / take‑profit and alerts at every rerun
TradingModule.check_stop_loss_take_profit(st.session_state.username)
check_price_alerts(st.session_state.username)

# ------------------------------------------------------------------
# UI THEME
# ------------------------------------------------------------------
theme = st.sidebar.radio("🎨 Theme", ["dark", "light"], horizontal=True, index=0 if st.session_state.get("theme","dark")=="dark" else 1)
st.session_state.theme = theme

if theme == "light":
    bg_style = "background: linear-gradient(135deg, #f0f2f6, #ffffff); color: #111;"
    sidebar_style = "background: rgba(255,255,255,0.9);"
else:
    bg_style = "background: linear-gradient(135deg, #0a0a1a, #1a1a3a, #2a2a4a); color: #e0e0e0;"
    sidebar_style = "background: rgba(20,20,40,0.85); backdrop-filter: blur(12px); border-right: 1px solid rgba(255,255,255,0.1);"

st.markdown(f"""
<style>
    .stApp {{ {bg_style} }}
    section[data-testid="stSidebar"] {{ {sidebar_style} }}
    h1,h2,h3 {{ font-family: 'Segoe UI', sans-serif; font-weight: 600; background: linear-gradient(90deg, #00d2ff, #3a7bd5); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }}
    .glass-card {{ background: rgba(255,255,255,0.06); backdrop-filter: blur(16px); border-radius:18px; border:1px solid rgba(255,255,255,0.1); padding:24px; margin:12px 0; box-shadow:0 12px 40px rgba(0,0,0,0.5); }}
    .metric-box {{ background: rgba(255,255,255,0.1); border-radius:14px; padding:18px; margin:6px 0; text-align:center; font-weight:bold; border:1px solid rgba(255,255,255,0.15); }}
    div.stButton > button {{ background: linear-gradient(45deg, #ff416c, #ff4b2b); border:none; color:white; padding:12px 28px; font-size:16px; font-weight:bold; border-radius:50px; box-shadow:0 0 20px rgba(255,75,43,0.5); transition:all 0.3s ease; cursor:pointer; letter-spacing:0.5px; text-transform:uppercase; width:100%; border:1px solid rgba(255,255,255,0.2); }}
    div.stButton > button:hover {{ transform:translateY(-2px); box-shadow:0 0 30px rgba(255,75,43,0.8); }}
    .stForm button {{ background: linear-gradient(45deg, #00b4db, #0083b0) !important; }}
</style>""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# DASHBOARD
# ------------------------------------------------------------------
if mode == "📊 Dashboard":
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("Dashboard Overview")
    balance = MobileWallet.get_balance(st.session_state.username)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Wallet Balance", f"${balance:,.2f}")
    with col2:
        forex_df = st.session_state.forex_data
        top_mover = ForexEngine.get_summary(forex_df).sort_values("Change %", key=lambda x: x.str.rstrip('%').astype(float), ascending=False).iloc[0]
        st.metric("Top Forex Mover", top_mover["Pair"], f"{top_mover['Change %']}%")
    with col3:
        crypto_df = st.session_state.crypto_live_prices
        if crypto_df is not None:
            best = crypto_df.loc[crypto_df['24h Change %'].idxmax()]
            st.metric("Top Crypto", best['Coin'], f"{best['24h Change %']}%")
    sentiment = fetch_market_sentiment()
    st.metric("Market Sentiment", "Bullish" if sentiment>0 else "Bearish" if sentiment<0 else "Neutral")
    st.line_chart(forex_df.set_index("Time")[["EUR/USD", "GBP/USD"]])
    if crypto_df is not None:
        st.dataframe(crypto_df, use_container_width=True, hide_index=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------
# FOREX PRO
# ------------------------------------------------------------------
elif mode == "💱 Forex Pro":
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("💹 Forex Pro")
    forex_df = ForexEngine.get_live_data(use_real=st.session_state.use_real_forex)
    st.session_state.forex_data = forex_df
    summary = ForexEngine.get_summary(forex_df)
    cols = st.columns(len(summary))
    for i, row in summary.iterrows():
        with cols[i]:
            color = "#00ff88" if row["Change"] >= 0 else "#ff4b4b"
            st.markdown(f"""<div class="metric-box">
                <span style="font-size:18px;">{row['Pair']}</span><br>
                <span style="font-size:24px; color:{color};">{row['Last']}</span><br>
                <span style="font-size:14px; color:{color};">{row['Change']} ({row['Change %']})</span>
            </div>""", unsafe_allow_html=True)
    st.line_chart(forex_df.set_index("Time"))
    pair_hist = st.selectbox("DB History", ForexEngine.PAIRS)
    hist_df = ForexEngine.get_history(pair_hist, 30)
    if not hist_df.empty:
        st.line_chart(hist_df.set_index("timestamp"))
    st.bar_chart(st.session_state.forex_volume.set_index("Time"))
    st.table(ForexEngine.get_correlation_matrix(forex_df))
    if st.button("🔄 Refresh Live Data"):
        st.session_state.forex_data = ForexEngine.get_live_data(use_real=st.session_state.use_real_forex)
        st.session_state.forex_volume = ForexEngine.get_volume()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------
# CRYPTO TRACKER
# ------------------------------------------------------------------
elif mode == "₿ Crypto Tracker":
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("₿ Live Crypto Prices")
    live_df = st.session_state.crypto_live_prices
    if live_df is not None:
        cols = st.columns(len(live_df))
        for i, row in live_df.iterrows():
            with cols[i]:
                change_color = "green" if row["24h Change %"] >= 0 else "red"
                st.markdown(f"""<div class="metric-box">
                    <span style="font-size:18px;">{row['Coin']}</span><br>
                    <span style="font-size:22px;">${row['Price (USD)']:,.2f}</span><br>
                    <span style="color:{change_color};">{row['24h Change %']}%</span>
                </div>""", unsafe_allow_html=True)
    else:
        st.warning("Could not fetch prices.")
    if st.button("🔄 Refresh Crypto"):
        st.session_state.crypto_live_prices = CryptoEngine.fetch_prices()
        st.rerun()
    coin_hist = st.selectbox("Select coin", CRYPTO_COINS, format_func=lambda x: CRYPTO_NAMES[x])
    hist = CryptoEngine.get_historical(coin_hist, 7)
    if hist is not None:
        st.line_chart(hist)
    with st.expander("🥩 Crypto Staking Simulator"):
        stake_coin = st.selectbox("Coin to stake", CRYPTO_COINS, format_func=lambda x: CRYPTO_NAMES[x])
        stake_amount = st.number_input("Amount", min_value=0.01, value=1.0)
        apy = st.slider("Estimated APY (%)", 0.0, 50.0, 5.0)
        days = st.slider("Staking period (days)", 1, 365, 30)
        earnings = stake_amount * (apy/100) * (days/365)
        st.metric("Estimated Earnings", f"${earnings:,.2f}")
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------
# JUP AI
# ------------------------------------------------------------------
elif mode == "🤖 Jup AI":
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("🤖 Jup AI · Trading Intelligence")
    sentiment = fetch_market_sentiment()
    st.metric("News Sentiment", "Bullish" if sentiment>0 else "Bearish" if sentiment<0 else "Neutral")
    news = [
        "Fed signals possible rate cut in next meeting.",
        "Oil prices surge on supply disruption fears.",
        "BTC whales accumulate ahead of halving event.",
        "UGX weakens on political uncertainty."
    ]
    for item in news:
        st.info(item)
    market = st.radio("Market", ["Forex", "Crypto"], horizontal=True)
    if market == "Forex":
        pair = st.selectbox("Select currency pair", ForexEngine.PAIRS)
        df = st.session_state.forex_data
        signals = TradingSignals.generate_signals(df, pair)
        buy_signals = sum(1 for s in signals if s[0]=="BUY")
        sell_signals = sum(1 for s in signals if s[0]=="SELL")
        if buy_signals > sell_signals:
            decision = "BUY"
        elif sell_signals > buy_signals:
            decision = "SELL"
        else:
            decision = "HOLD"
        st.markdown(f"### Decision: **{decision}**")
        prices = df[pair].values
        equity = backtest_rsi_strategy(prices)
        st.line_chart(pd.DataFrame({"Equity": equity}))
    else:
        coin = st.selectbox("Select coin", CRYPTO_COINS, format_func=lambda x: CRYPTO_NAMES[x])
        live = st.session_state.crypto_live_prices
        if live is not None:
            row = live[live['Coin']==CRYPTO_NAMES[coin]]
            if not row.empty:
                change = row.iloc[0]['24h Change %']
                if change > 3:
                    decision = "SELL"
                elif change < -3:
                    decision = "BUY"
                else:
                    decision = "HOLD"
                st.markdown(f"### Decision: **{decision}**")
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------
# TRADING
# ------------------------------------------------------------------
elif mode == "📈 Trading":
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("📈 Virtual Trading Terminal")
    balance = MobileWallet.get_balance(st.session_state.username)
    st.metric("Available Capital", f"${balance:,.2f}")

    with st.expander("➕ New Trade"):
        market = st.selectbox("Market", ["Forex", "Crypto"])
        if market == "Forex":
            symbol = st.selectbox("Pair", ForexEngine.PAIRS)
            latest_price = st.session_state.forex_data.iloc[-1][symbol]
        else:
            symbol = st.selectbox("Coin", CRYPTO_COINS, format_func=lambda x: CRYPTO_NAMES[x])
            live = st.session_state.crypto_live_prices
            if live is not None:
                row = live[live['Coin']==CRYPTO_NAMES[symbol]]
                latest_price = row.iloc[0]['Price (USD)'] if not row.empty else 0
            else:
                latest_price = 0
        trade_type = st.selectbox("Direction", ["buy", "sell"])
        amount = st.number_input("Amount (units)", min_value=0.01, value=1.0, step=0.1)
        leverage = st.selectbox("Leverage", [1, 2, 5, 10], index=0)
        stop_loss = st.number_input("Stop‑Loss price (optional)", value=0.0, step=0.01)
        take_profit = st.number_input("Take‑Profit price (optional)", value=0.0, step=0.01)
        total_value = amount * latest_price * leverage
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Current Price", f"${latest_price:,.4f}")
        with col2:
            st.metric("Total Exposure", f"${total_value:,.2f}")
        if st.button("Execute Trade"):
            if total_value > balance:
                st.error("Insufficient balance.")
            else:
                TradingModule.open_trade(
                    st.session_state.username, symbol, trade_type, amount, latest_price, leverage,
                    stop_loss if stop_loss > 0 else None,
                    take_profit if take_profit > 0 else None)
                st.success(f"{trade_type.upper()} order placed.")
                st.rerun()

    positions = TradingModule.get_open_positions(st.session_state.username)
    if not positions.empty:
        total_exposure = 0
        for _, pos in positions.iterrows():
            total_exposure += pos['amount'] * pos['open_price'] * pos['leverage']
        st.metric("Total Exposure", f"${total_exposure:,.2f}")
        st.metric("Margin Level", f"{(balance / total_exposure * 100) if total_exposure else 100:.1f}%")

    st.subheader("📊 Open Positions")
    if not positions.empty:
        for idx, pos in positions.iterrows():
            with st.container():
                cols = st.columns([2,1,1,1,1,1])
                with cols[0]:
                    st.write(f"**{pos['symbol']}** ({pos['trade_type']})")
                with cols[1]:
                    st.write(f"Open: {pos['open_price']}")
                with cols[2]:
                    st.write(f"Amount: {pos['amount']}")
                with cols[3]:
                    if pos['symbol'] in ForexEngine.PAIRS:
                        current_price = st.session_state.forex_data.iloc[-1][pos['symbol']]
                    else:
                        live = st.session_state.crypto_live_prices
                        if live is not None:
                            row = live[live['Coin']==CRYPTO_NAMES.get(pos['symbol'], '')]
                            current_price = row.iloc[0]['Price (USD)'] if not row.empty else pos['open_price']
                        else:
                            current_price = pos['open_price']
                    upnl = (current_price - pos['open_price']) * pos['amount'] * pos['leverage'] if pos['trade_type']=='buy' else (pos['open_price'] - current_price) * pos['amount'] * pos['leverage']
                    color = "green" if upnl >=0 else "red"
                    st.markdown(f"Unreal. P&L: <span style='color:{color}'>${upnl:.2f}</span>", unsafe_allow_html=True)
                with cols[4]:
                    if st.button("Close", key=f"close_{pos['id']}"):
                        result, msg = TradingModule.close_trade(pos['id'], current_price)
                        if result:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()
    else:
        st.info("No open positions.")

    st.subheader("🔔 Set Price Alert")
    with st.form("alert_form"):
        alert_symbol = st.selectbox("Symbol", ForexEngine.PAIRS + list(CRYPTO_NAMES.values()))
        alert_price = st.number_input("Target price", value=0.0)
        alert_direction = st.selectbox("When price is", ["above", "below"])
        if st.form_submit_button("Create Alert"):
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO alerts (username, symbol, price, direction) VALUES (?, ?, ?, ?)",
                      (st.session_state.username, alert_symbol, alert_price, alert_direction))
            conn.commit()
            st.success("Alert set!")

    st.subheader("📜 Trade History")
    history = TradingModule.get_trade_history(st.session_state.username)
    if not history.empty:
        csv = history.to_csv(index=False)
        b64 = base64.b64encode(csv.encode()).decode()
        href = f'<a href="data:file/csv;base64,{b64}" download="trades.csv">📥 Download CSV</a>'
        st.markdown(href, unsafe_allow_html=True)
        st.dataframe(history[['symbol','trade_type','open_price','close_price','amount','leverage','pnl','status','timestamp']], use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------
# MOBILE WALLET
# ------------------------------------------------------------------
elif mode == "💳 Mobile Wallet":
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("💳 Mobile Wallet")
    balance = MobileWallet.get_balance(st.session_state.username)
    st.metric("Current Balance", f"${balance:,.2f}")
    with st.expander("⚡ Instant Top‑Up (Simulated)"):
        quick_amount = st.number_input("Amount to add", min_value=1.0, value=100.0, step=10.0)
        if st.button("Add Funds Now"):
            ref = f"TOPUP{datetime.now().strftime('%Y%m%d%H%M%S')}"
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''INSERT INTO wallet_transactions
                         (username, type, amount, phone, provider, reference, status, timestamp)
                         VALUES (?, 'deposit', ?, 'instant', 'Simulated', ?, 'completed', ?)''',
                      (st.session_state.username, quick_amount, ref, datetime.now().isoformat()))
            conn.commit()
            st.success(f"${quick_amount:,.2f} added!")
            st.rerun()
    tab1, tab2 = st.tabs(["💰 Deposit", "💸 Withdraw"])
    with tab1:
        with st.form("deposit_form"):
            phone = st.text_input("Phone number")
            amount = st.number_input("Amount", min_value=1.0, step=10.0)
            provider = st.selectbox("Provider", MobileWallet.PROVIDERS)
            if st.form_submit_button("Request Deposit"):
                ref = MobileWallet.deposit_request(st.session_state.username, phone, amount, provider)
                st.session_state.deposit_ref = ref
                st.success(f"Reference: {ref}")
        if 'deposit_ref' in st.session_state:
            confirm_ref = st.text_input("Confirm reference", key="dep_confirm")
            if st.button("✅ Confirm Deposit"):
                if confirm_ref == st.session_state.deposit_ref:
                    MobileWallet.confirm_deposit(confirm_ref)
                    st.success("Deposit confirmed!")
                    del st.session_state.deposit_ref
                    st.rerun()
                else:
                    st.error("Invalid reference")
    with tab2:
        with st.form("withdraw_form"):
            phone = st.text_input("Phone number", key="w_phone")
            amount = st.number_input("Amount", min_value=1.0, step=10.0, key="w_amount")
            provider = st.selectbox("Provider", MobileWallet.PROVIDERS, key="w_provider")
            if st.form_submit_button("Request Withdrawal"):
                ref, msg = MobileWallet.withdraw_request(st.session_state.username, phone, amount, provider)
                if ref is None:
                    st.error(msg)
                else:
                    st.session_state.withdraw_ref = ref
                    st.success(f"Reference: {ref}")
        if 'withdraw_ref' in st.session_state:
            confirm_ref = st.text_input("Confirm reference", key="wth_confirm")
            if st.button("✅ Confirm Withdrawal"):
                if confirm_ref == st.session_state.withdraw_ref:
                    MobileWallet.confirm_withdrawal(confirm_ref)
                    st.success("Withdrawal successful!")
                    del st.session_state.withdraw_ref
                    st.rerun()
                else:
                    st.error("Invalid reference")
    st.subheader("Transaction History")
    txn_df = MobileWallet.get_transactions(st.session_state.username)
    if not txn_df.empty:
        def color_status(val):
            color = 'green' if val == 'completed' else 'orange'
            return f'color: {color}'
        styled = txn_df.style.map(color_status, subset=['status'])
        st.dataframe(styled, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------
# LEADERBOARD
# ------------------------------------------------------------------
if st.button("🏆 Leaderboard"):
    conn = get_db_connection()
    users = get_all_users()
    balances = [(row['username'], MobileWallet.get_balance(row['username'])) for _, row in users.iterrows()]
    balances.sort(key=lambda x: x[1], reverse=True)
    st.subheader("Top Traders")
    for i, (user, bal) in enumerate(balances[:10]):
        st.write(f"{i+1}. {user}: ${bal:,.2f}")