<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Solana Portfolio Risk Analyzer</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a1a; color: #e0e0e0; margin: 20px; }
        .container { max-width: 1200px; margin: auto; }
        .card { background: rgba(255,255,255,0.06); backdrop-filter: blur(12px); border-radius: 16px; padding: 20px; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.1); }
        label, input, select, button { color: #fff; }
        input, select { background: #1e1e2f; border: 1px solid #333; padding: 8px; border-radius: 6px; }
        button { background: linear-gradient(45deg, #ff416c, #ff4b2b); border: none; padding: 12px 28px; border-radius: 50px; cursor: pointer; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; border-bottom: 1px solid #333; text-align: right; }
        .risk-high { color: #F44336; } .risk-medium { color: #FF9800; } .risk-low { color: #4CAF50; }
        .metric { background: rgba(255,255,255,0.1); border-radius: 10px; padding: 15px; text-align: center; margin: 10px 0; }
        .metrics-row { display: flex; justify-content: space-between; gap: 10px; }
    </style>
</head>
<body>
<div class="container">
    <h1>🪐 Jupiter Solana Portfolio Risk Analyzer</h1>

    <form method="POST">
        <div class="card">
            <label>Jupiter API Key (optional):</label>
            <input type="password" name="jup_api_key" value="{{ api_key }}">
        </div>

        <div class="card">
            <label>Input Method:</label>
            <select name="mode" onchange="this.form.submit()">
                <option value="manual" {% if mode == 'manual' %}selected{% endif %}>Manual Entry</option>
                <option value="wallet" {% if mode == 'wallet' %}selected{% endif %}>Wallet Import (Simulation)</option>
            </select>
        </div>

        {% if mode == 'manual' %}
        <div class="card">
            <h3>Select Assets and Balances</h3>
            {% for name, data in tokens.items() %}
            <div style="margin-bottom:10px;">
                <label>
                    <input type="checkbox" name="token" value="{{ name }}"
                           {% if name in ["Solana (SOL)", "USD Coin (USDC)"] %}checked{% endif %}>
                    {{ name }}
                </label>
                <input type="number" step="0.001" name="amount_{{ name }}" placeholder="Amount" style="margin-left:20px;"
                       value="{% if name in ["Solana (SOL)", "USD Coin (USDC)"] %}10{% else %}0{% endif %}">
            </div>
            {% endfor %}
        </div>
        {% elif mode == 'wallet' %}
        <div class="card">
            <label>Wallet Address:</label>
            <input type="text" name="wallet_address" value="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU" style="width:400px;">
            <p style="font-size:0.8em;">Simulated wallet with pre‑loaded balances.</p>
        </div>
        {% endif %}

        <button type="submit">Analyze Portfolio</button>
    </form>

    {% if error %}
    <div class="card" style="color:#F44336;">{{ error }}</div>
    {% endif %}

    {% if results %}
    <div class="metrics-row">
        <div class="metric">
            <div>Total Value</div>
            <div style="font-size:1.5em;">${{ "{:,.2f}".format(results.total_val) }}</div>
        </div>
        <div class="metric">
            <div>Risk Score</div>
            <div style="font-size:1.5em;" class="{% if results.risk_score > 7 %}risk-high{% elif results.risk_score > 4 %}risk-medium{% else %}risk-low{% endif %}">
                {{ results.risk_score }}/10 {{ results.risk_label }}
            </div>
        </div>
        <div class="metric">
            <div>Largest Holding</div>
            <div style="font-size:1.5em;">{{ results.largest_holding }}</div>
        </div>
        <div class="metric">
            <div>Assets Tracked</div>
            <div style="font-size:1.5em;">{{ results.assets_count }}</div>
        </div>
    </div>

    <div class="card">
        <div id="chart_assets"></div>
        <script>var chart = {{ results.chart_assets | safe }}; Plotly.newPlot('chart_assets', chart.data, chart.layout);</script>
    </div>

    <div class="card">
        <div id="chart_risk"></div>
        <script>var chart2 = {{ results.chart_risk | safe }}; Plotly.newPlot('chart_risk', chart2.data, chart2.layout);</script>
    </div>

    <div class="card">
        <h3>Asset Breakdown</h3>
        <table>
            <tr><th>Token</th><th>Type</th><th>Amount</th><th>Price</th><th>Value</th><th>Allocation</th><th>Risk</th></tr>
            {% for row in results.table_data %}
            <tr>
                <td>{{ row.Token }}</td>
                <td>{{ row.Type }}</td>
                <td>{{ row.Amount }}</td>
                <td>${{ "{:,.4f}".format(row["Price (USD)"]) }}</td>
                <td>${{ "{:,.2f}".format(row["Value (USD)"]) }}</td>
                <td>{{ "{:.2f}".format(row["Allocation (%)"]) }}%</td>
                <td class="{% if row['Risk Profile'] == 'High' %}risk-high{% elif row['Risk Profile'] == 'Medium' %}risk-medium{% else %}risk-low{% endif %}">{{ row['Risk Profile'] }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <div class="card">
        <h3>🤖 Smart Portfolio Advisor Insights</h3>
        <div style="white-space: pre-line;">{{ results.insights }}</div>
    </div>
    {% endif %}
</div>
</body>
</html>