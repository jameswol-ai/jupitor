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
# VERCEL SPEED INSIGHTS
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
# AUTHENTICATION & 2FA (unchanged logic)
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
    # Fallback demo (consider moving to secrets)
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
# EMAIL (unchanged)
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
# MOBILE WALLET (unchanged)
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
# FOREX ENGINE (unchanged)
# ------------------------------------------------------------------
# ... keep the entire ForexEngine, TradingSignals, ForexForecast,
# CryptoEngine, CryptoForecast, TradingModule classes exactly as before.
# They are omitted here for brevity but must remain in the final file.
# (Copy them from your original streamlit_app.py)

# ------------------------------------------------------------------
# TRADING MODULE (unchanged)
# ------------------------------------------------------------------
# ... same as before

# ------------------------------------------------------------------
# PRICE ALERTS (unchanged)
# ------------------------------------------------------------------
# ...

# ------------------------------------------------------------------
# BACKTESTING (unchanged)
# ------------------------------------------------------------------
# ...

# ------------------------------------------------------------------
# SENTIMENT (unchanged)
# ------------------------------------------------------------------
# ...

# ------------------------------------------------------------------
# SIDEBAR AUTHENTICATION – NEW
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
        # Provide a way to request OTP (outside the form)
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
# REST OF THE APP (exactly as before, after login)
# ------------------------------------------------------------------
# (Copy everything from the original file below the st.stop() line,
#  including the logout button, navigation, dashboard, etc.
#  The sidebar should now show user info and logout button.)

# --- LOGOUT (in sidebar) ---
def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

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
            # ... keep admin panel as before
    if st.button("🚪 Logout"):
        logout()
    st.caption("v12 · PWA Ready")

# ... (the rest of the dashboard, forex, crypto, trading, wallet, leaderboard code remains identical)