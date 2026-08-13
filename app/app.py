from flask import Flask
from app.routes.payment import payment_bp
from app.routes.analytics_route import analytics_bp

app = Flask(__name__)

# Register Blueprint Webhook & Analytics
app.register_blueprint(payment_bp)
app.register_blueprint(analytics_bp)

if __name__ == '__main__':
    print("Server BoonTrack Listener Berjalan di Port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)