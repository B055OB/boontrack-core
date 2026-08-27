"""
Legacy Flask micro-app (Note: Main production server runs on aiohttp in app/main.py).
"""
import sys
import os

from flask import Flask
from app.routes.analytics_route import analytics_bp

app = Flask(__name__)
app.register_blueprint(analytics_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
