import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data.db')}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Simulator intervals (seconds)
    SIM_PRICE_JITTER_SEC = int(os.environ.get("SIM_PRICE_JITTER_SEC", "10"))
    SIM_STOCK_EVENT_SEC = int(os.environ.get("SIM_STOCK_EVENT_SEC", "8"))

    # Industry 4.0 toggles
    ENABLE_ANOMALY_GUARD = os.environ.get("ENABLE_ANOMALY_GUARD", "1") == "1"
    ANOMALY_WINDOW = int(os.environ.get("ANOMALY_WINDOW", "50"))
    ANOMALY_ZSCORE = float(os.environ.get("ANOMALY_ZSCORE", "3.0"))

    # MQTT (optional)
    MQTT_ENABLED = os.environ.get("MQTT_ENABLED", "0") == "1"
    MQTT_BROKER = os.environ.get("MQTT_BROKER", "broker.hivemq.com")
    MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
    MQTT_USERNAME = os.environ.get("MQTT_USERNAME")
    MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
    MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "iot-sheet-client")

    # ERP webhook (optional)
    ERP_WEBHOOK_URL = os.environ.get("ERP_WEBHOOK_URL")


