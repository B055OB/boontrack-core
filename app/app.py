import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from routes.payment import payment_bp
from routes.analytics_route import analytics_bp

app = Flask(__name__)

app.register_blueprint(payment_bp)
app.register_blueprint(analytics_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)