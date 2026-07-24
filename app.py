import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# Page configuration
st.set_page_config(
    page_title="Solana Portfolio Risk Analyzer",
    page_icon="🪐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CURATED SOLANA TOKENS (Fallback database) ---
# Keeping a curated list guarantees the app functions immediately without needing an API key.
DEFAULT_TOKENS = {
    "Solana (SOL)": {"mint": "So11111111111111111111111111111111111111112", "risk": "Low", "price_default": 140.0, "type": "Native L1"},
    "USD Coin (USDC)": {"mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "risk": "Low", "price_default": 1.0, "type": "Stablecoin"},
    "Tether (USDT)": {"mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "risk": "Low", "price_default": 1.0, "type": "Stablecoin"},
    "Jupiter (JUP)": {"mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", "risk": "Medium", "price_default": 0.95, "type": "DeFi Utility"},
    "Pyth Network (PYTH)": {"mint": "HZ1JbNs2ST4wwE7as979mJ6Y8XFR3EnZ5Rdf8S6ZfLNp", "risk": "Medium", "price_default": 0.35, "type": "Oracle / Infra"},
    "Jito (JTO)": {"mint": "jtojtome5kxvXzKSpRndmcg9fK5S8fBfD8LscV3N5K6", "risk": "Medium", "price_default": 2.20, "type": "Liquid Staking"},
    "Dogwifhat (WIF)": {"mint": "EKpQGSJmg823YEV4L6p3W5ij37mN2Y8SmW91mZ366xoV", "risk": "High", "price_default": 2.50, "type": "Memecoin"},
    "Bonk (BONK)": {"mint": "DezXAZ8z7PnrFcPyg7GRt6R3G338gMt858H8VXHzpHqg", "risk": "High", "price_default": 0.000022, "type": "Memecoin"},
    "Popcat (POPCAT)": {"mint": "7GCih6b9GMSr0979L6vvwY6Y3089mZ366xoV56Y8xoV", "risk": "High", "price_default": 1.10, "type": "Memecoin"}
}

# --- UTILITY FUNCTIONS ---

@st.cache_data(ttl=300)
def fetch_jupiter_prices(mints, api_key=None):
    """
    Attempts to fetch live token prices from the Jupiter Price API.
    If no API key is set, it falls back to default values.
    """
    prices = {}

    # Pre-populate with defaults
    for name, data in DEFAULT_TOKENS.items():
        prices[data["mint"]] = data["price_default"]

    if not api_key:
        return prices

    try:
        url = f"https://api.jup.ag/price/v3?ids={','.join(mints)}"
        headers = {"x-api-key": api_key}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json().get("data", {})
            for mint, token_data in data.items():
                if token_data and "price" in token_data:
                    prices[mint] = float(token_data["price"])
    except Exception as e:
        st.sidebar.warning("Failed to fetch live prices. Falling back to default baseline values.")

    return prices

def generate_ai_insights(portfolio_df, openrouter_key=None):
    """
    Generates tailored advice based on the risk composition.
    Uses real LLM integration if OpenRouter Key is configured, otherwise fallback to deterministic system.
    """
    low_pct = portfolio_df[portfolio_df['Risk Profile'] == 'Low']['Allocation (%)'].sum()
    med_pct = portfolio_df[portfolio_df['Risk Profile'] == 'Medium']['Allocation (%)'].sum()
    high_pct = portfolio_df[portfolio_df['Risk Profile'] == 'High']['Allocation (%)'].sum()

    # Calculate weighted risk score (0-100 scale)
    risk_score = (low_pct * 1 + med_pct * 5 + high_pct * 10) / 10

    if openrouter_key:
        try:
            # Structuring payload for OpenRouter
            prompt = (
                f"Act as an expert Solana Web3 Portfolio Advisor. Analyze this portfolio composition: "
                f"Low Risk (stables/SOL): {low_pct:.1f}%, "
                f"Medium Risk (utility alts): {med_pct:.1f}%, "
                f"High Risk (memecoins/microcaps): {high_pct:.1f}%. "
                f"The aggregate risk score is {risk_score:.1f}/10. "
                f"Provide 3 actionable risk mitigation or restructuring tips specific to the Solana ecosystem in a clean bullet format."
            )
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemini-2.5-flash",
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=10
            )
            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content']
        except Exception:
            pass

    # Deterministic fallback insights
    if risk_score > 7.0:
        return (
            "⚠️ **Aggressive Risk Exposure Detected**\n\n"
            "- **De-risk into Core Assets:** Over 70% of your holdings are allocated to highly volatile high-risk categories. Consider shifting profits into native SOL or established stablecoins (USDC/USDT).\n"
            "- **Set Stop-Losses:** Volatility on Solana memecoins can exceed 50% in hours. Ensure you have targeted exit points.\n"
            "- **Yield Opportunities:** Move some stable holdings to trusted Solana yield lending protocols (like Kamino or Marginfi) to build passive baselines."
        )
    elif risk_score > 4.0:
        return (
            "⚖️ **Balanced Growth Portfolio**\n\n"
            "- **Optimized Ecosystem Allocation:** Your mix is healthy. You have a reliable baseline in SOL/stables while capturing growth in major Solana altcoins (JUP, PYTH).\n"
            "- **Rebalancing Strategy:** Periodically lock in profits from high-performing speculative plays back into your 'Low Risk' bucket to maintain your target asset allocation.\n"
            "- **Governance Engagement:** If holding JUP or JTO, consider staking them on their native platforms to qualify for potential governance benefits and ecological distributions."
        )
    else:
        return (
            "🛡️ **Conservative / Defensive Allocation**\n\n"
            "- **Capital Preservation Focus:** Excellent baseline stability. Your portfolio is highly resilient to market drawdowns.\n"
            "- **Liquidity Optimization:** Consider liquid-staking your SOL through platforms like Jito (JTO) or Marinade to earn network yields while keeping assets fluid.\n"
            "- **Strategic Allocation:** If your risk appetite permits, allocate a small percentage (2-5%) to core Solana ecosystem infrastructure protocols to gain exposure to decentralized network growth."
        )

# --- SIDEBAR CONFIGURATION ---
st.sidebar.title("🪐 Jupiter Analyzer Config")
st.sidebar.markdown("Configure external integrations for live data & deeper intelligence.")

# API Key inputs
jup_api_key = st.sidebar.text_input("Jupiter Developer API Key (Optional)", type="password", help="Enables live pricing via Jupiter V3 API")
openrouter_key = st.sidebar.text_input("OpenRouter API Key (Optional)", type="password", help="Enables customized LLM insights via OpenRouter models")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛠️ Input Method")
app_mode = st.sidebar.radio("Choose how to load your portfolio:", ["Manual Entry", "Wallet Import (Simulation)"])

# --- MAIN APP LOGIC ---
st.title("🪐 Jupiter Solana Portfolio Risk Analyzer")
st.markdown("Analyze asset allocations, monitor volatility buckets, and secure customized risk reports.")

# Fetch prices based on configuration
mints = [data["mint"] for data in DEFAULT_TOKENS.values()]
prices_db = fetch_jupiter_prices(mints, api_key=jup_api_key if jup_api_key else None)

# Initialize portfolio data
portfolio_items = []

if app_mode == "Manual Entry":
    st.subheader("📝 Customize Your Manual Portfolio")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Select Assets and Balances**")
        for token_name, data in DEFAULT_TOKENS.items():
            # Create input check and balance input side by side
            c_check, c_amount = st.columns([1, 2])
            with c_check:
                is_selected = st.checkbox(token_name, value=(token_name in ["Solana (SOL)", "USD Coin (USDC)"]))
            with c_amount:
                amount = st.number_input(f"Amount of {token_name.split(' ')[0]}", min_value=0.0, value=10.0 if is_selected else 0.0, step=1.0, key=f"amt_{token_name}")

            if is_selected and amount > 0:
                price = prices_db.get(data["mint"], data["price_default"])
                portfolio_items.append({
                    "Token": token_name,
                    "Amount": amount,
                    "Price (USD)": price,
                    "Value (USD)": amount * price,
                    "Risk Profile": data["risk"],
                    "Type": data["type"]
                })

elif app_mode == "Wallet Import (Simulation)":
    st.subheader("🔑 Import Solana Wallet Address")
    wallet_address = st.text_input("Enter Solana Wallet Public Address", "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", help="Example uses the Jupiter Treasury address")

    if wallet_address:
        st.info("💡 Real-time wallet token scraping usually requires a Solana RPC Node. This dashboard is simulating imports using real-time values from Jupiter.")
        # Generates realistic allocations for the demo run
        simulated_allocations = {
            "Solana (SOL)": 500.0,
            "USD Coin (USDC)": 15000.0,
            "Jupiter (JUP)": 8000.0,
            "Pyth Network (PYTH)": 4000.0,
            "Dogwifhat (WIF)": 150.0
        }
        for token_name, amount in simulated_allocations.items():
            data = DEFAULT_TOKENS[token_name]
            price = prices_db.get(data["mint"], data["price_default"])
            portfolio_items.append({
                "Token": token_name,
                "Amount": amount,
                "Price (USD)": price,
                "Value (USD)": amount * price,
                "Risk Profile": data["risk"],
                "Type": data["type"]
            })

# --- DATA PROCESS & RENDERING ---
if portfolio_items:
    df = pd.DataFrame(portfolio_items)
    total_val = df["Value (USD)"].sum()
    df["Allocation (%)"] = (df["Value (USD)"] / total_val) * 100

    # Calculate Risk Score
    low_pct = df[df['Risk Profile'] == 'Low']['Allocation (%)'].sum()
    med_pct = df[df['Risk Profile'] == 'Medium']['Allocation (%)'].sum()
    high_pct = df[df['Risk Profile'] == 'High']['Allocation (%)'].sum()
    risk_score = (low_pct * 1 + med_pct * 5 + high_pct * 10) / 10

    # Overview Cards
    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Portfolio Value", f"${total_val:,.2f}")

    # Color-coded risk assessment score
    if risk_score > 7.0:
        m2.metric("Aggregate Risk Score", f"{risk_score:.1f} / 10", "High Risk 🔥")
    elif risk_score > 4.0:
        m2.metric("Aggregate Risk Score", f"{risk_score:.1f} / 10", "Moderate Risk ⚖️")
    else:
        m2.metric("Aggregate Risk Score", f"{risk_score:.1f} / 10", "Low Risk 🛡️")

    m3.metric("Largest Holding", f"{df.loc[df['Value (USD)'].idxmax()]['Token'].split(' ')[0]}")
    m4.metric("Assets Tracked", f"{len(df)}")

    # Charts Division
    st.markdown("---")
    char_col1, char_col2 = st.columns(2)

    with char_col1:
        st.subheader("📊 Asset Allocation Breakdown")
        fig_assets = px.pie(
            df, 
            values='Value (USD)', 
            names='Token', 
            hole=0.4,
            color_discrete_sequence=px.colors.sequential.Agsunset
        )
        fig_assets.update_layout(margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_assets, use_container_width=True)

    with char_col2:
        st.subheader("⚠️ Risk Profile Composition")
        risk_grouped = df.groupby('Risk Profile').sum(numeric_only=True).reset_index()
        fig_risk = px.bar(
            risk_grouped,
            x='Risk Profile',
            y='Value (USD)',
            color='Risk Profile',
            color_discrete_map={'Low': '#4CAF50', 'Medium': '#FF9800', 'High': '#F44336'},
            category_orders={'Risk Profile': ['Low', 'Medium', 'High']}
        )
        fig_risk.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
        st.plotly_chart(fig_risk, use_container_width=True)

    # Data Table View
    st.subheader("📋 Asset Breakdown details")
    st.dataframe(
        df[["Token", "Type", "Amount", "Price (USD)", "Value (USD)", "Allocation (%)", "Risk Profile"]].style.format({
            "Price (USD)": "${:,.4f}",
            "Value (USD)": "${:,.2f}",
            "Allocation (%)": "{:.2f}%"
        }),
        use_container_width=True
    )

    # Interactive AI Assistant Section
    st.markdown("---")
    st.subheader("🤖 Smart Portfolio Advisor Insights")

    with st.spinner("Analyzing allocation patterns..."):
        insights = generate_ai_insights(df, openrouter_key=openrouter_key if openrouter_key else None)
        st.markdown(insights)

else:
    st.warning("⚠️ No assets are active. Please select at least one token from the manual selection options or enter a wallet address.")