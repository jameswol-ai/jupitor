from flask import Flask, render_template, request
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
import json
import plotly.utils

app = Flask(__name__)

# --- CURATED SOLANA TOKENS (same as before) ---
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

# Simulated wallet balances (same as before)
SIMULATED_WALLET = {
    "Solana (SOL)": 500.0,
    "USD Coin (USDC)": 15000.0,
    "Jupiter (JUP)": 8000.0,
    "Pyth Network (PYTH)": 4000.0,
    "Dogwifhat (WIF)": 150.0
}

def fetch_prices(api_key=None):
    """Fetch live prices or fallback to defaults."""
    prices = {}
    for name, data in DEFAULT_TOKENS.items():
        prices[name] = data["price_default"]  # using token name as key for simplicity

    if api_key:
        try:
            mints = [data["mint"] for data in DEFAULT_TOKENS.values()]
            url = f"https://api.jup.ag/price/v3?ids={','.join(mints)}"
            headers = {"x-api-key": api_key}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()["data"]
                mint_to_name = {v["mint"]: k for k, v in DEFAULT_TOKENS.items()}
                for mint, token_data in data.items():
                    if token_data and "price" in token_data:
                        name = mint_to_name.get(mint)
                        if name:
                            prices[name] = float(token_data["price"])
        except:
            pass
    return prices

def generate_insights(risk_score, low_pct, med_pct, high_pct):
    """Deterministic fallback insights (LLM optional)."""
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

@app.route("/", methods=["GET", "POST"])
def index():
    # Default values
    portfolio_items = []
    results = None
    error = None
    api_key = request.form.get("jup_api_key", "").strip()
    mode = request.form.get("mode", "manual")

    # Fetch prices
    prices = fetch_prices(api_key if api_key else None)

    if request.method == "POST":
        if mode == "manual":
            selected_tokens = request.form.getlist("token")
            amounts = {}
            for token in selected_tokens:
                amt_str = request.form.get(f"amount_{token}", "0")
                try:
                    amount = float(amt_str)
                except:
                    amount = 0.0
                if amount > 0:
                    price = prices.get(token, DEFAULT_TOKENS[token]["price_default"])
                    portfolio_items.append({
                        "Token": token,
                        "Amount": amount,
                        "Price (USD)": price,
                        "Value (USD)": amount * price,
                        "Risk Profile": DEFAULT_TOKENS[token]["risk"],
                        "Type": DEFAULT_TOKENS[token]["type"]
                    })
        elif mode == "wallet":
            wallet = request.form.get("wallet_address", "")
            if wallet:
                # Use simulated wallet
                for token, amount in SIMULATED_WALLET.items():
                    price = prices.get(token, DEFAULT_TOKENS[token]["price_default"])
                    portfolio_items.append({
                        "Token": token,
                        "Amount": amount,
                        "Price (USD)": price,
                        "Value (USD)": amount * price,
                        "Risk Profile": DEFAULT_TOKENS[token]["risk"],
                        "Type": DEFAULT_TOKENS[token]["type"]
                    })
            else:
                error = "Please enter a wallet address."

        # Compute metrics if items exist
        if portfolio_items:
            df = pd.DataFrame(portfolio_items)
            total_val = df["Value (USD)"].sum()
            df["Allocation (%)"] = (df["Value (USD)"] / total_val) * 100

            low_pct = df[df['Risk Profile'] == 'Low']['Allocation (%)'].sum()
            med_pct = df[df['Risk Profile'] == 'Medium']['Allocation (%)'].sum()
            high_pct = df[df['Risk Profile'] == 'High']['Allocation (%)'].sum()
            risk_score = (low_pct * 1 + med_pct * 5 + high_pct * 10) / 10

            # Charts as JSON
            fig_assets = px.pie(df, values='Value (USD)', names='Token', hole=0.4,
                                color_discrete_sequence=px.colors.sequential.Agsunset)
            chart_assets = json.dumps(fig_assets, cls=plotly.utils.PlotlyJSONEncoder)

            risk_grouped = df.groupby('Risk Profile').sum(numeric_only=True).reset_index()
            fig_risk = px.bar(risk_grouped, x='Risk Profile', y='Value (USD)', color='Risk Profile',
                              color_discrete_map={'Low': '#4CAF50', 'Medium': '#FF9800', 'High': '#F44336'},
                              category_orders={'Risk Profile': ['Low', 'Medium', 'High']})
            chart_risk = json.dumps(fig_risk, cls=plotly.utils.PlotlyJSONEncoder)

            insights = generate_insights(risk_score, low_pct, med_pct, high_pct)

            # Convert df to dict for table
            table_data = df.to_dict(orient='records')

            results = {
                "total_val": total_val,
                "risk_score": risk_score,
                "risk_label": ("High Risk 🔥" if risk_score > 7 else "Moderate Risk ⚖️" if risk_score > 4 else "Low Risk 🛡️"),
                "largest_holding": df.loc[df['Value (USD)'].idxmax()]['Token'].split(' ')[0],
                "assets_count": len(df),
                "chart_assets": chart_assets,
                "chart_risk": chart_risk,
                "table_data": table_data,
                "insights": insights
            }

    return render_template("index.html",
                           tokens=DEFAULT_TOKENS,
                           results=results,
                           error=error,
                           api_key=api_key,
                           mode=mode)

# Required for Vercel
if __name__ == "__main__":
    app.run(debug=True)