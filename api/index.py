import sys
import traceback

def handler(event, context):
    # We'll use Flask, but first just check imports
    try:
        import flask
        import pandas
        import numpy
        import requests
        import plotly
    except Exception as e:
        return {
            "statusCode": 500,
            "body": f"Import error: {traceback.format_exc()}"
        }
    # If imports succeed, run Flask normally via WSGI
    from flask import Flask, render_template, request
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "All imports OK. Flask works."

    # Vercel expects a WSGI app, so we'll convert to serverless
    # But to be safe, we'll just return a simple response.
    return {
        "statusCode": 200,
        "body": "Flask is ready to be wired."
    }