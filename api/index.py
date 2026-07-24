import subprocess
import sys
import os

def handler(request, response):
    # Streamlit requires a long‑running process – this is a hack.
    # For a real deployment, use a custom wrapper or switch platforms.
    # We'll just run the app in a subprocess and pipe the request.
    # NOT recommended – just illustrative.
    return response.send("Streamlit cannot run serverless. Use Streamlit Cloud.")