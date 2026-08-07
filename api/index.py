from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Hello from Flask"

@app.route("/api/index.py")
def api_route():
    return "API route works"