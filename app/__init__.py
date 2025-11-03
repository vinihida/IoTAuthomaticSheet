import os
import threading
from queue import Queue
from typing import Dict, List

from flask import Flask
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from flask import Response, request


db = SQLAlchemy()
login_manager = LoginManager()


class SseBroker:
    """Simple in-process SSE broker using per-client queues."""

    def __init__(self) -> None:
        self._clients: List[Queue] = []
        self._lock = threading.Lock()

    def register(self) -> Queue:
        q: Queue = Queue()
        with self._lock:
            self._clients.append(q)
        return q

    def unregister(self, q: Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, event: Dict) -> None:
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(event)
                except Exception:
                    # Drop unresponsive client
                    try:
                        self._clients.remove(q)
                    except ValueError:
                        pass
        # Metrics hooks (optional)
        try:
            from flask import current_app
            if 'type' in event and hasattr(current_app, 'metrics'):
                if event['type'] == 'stock':
                    current_app.metrics['STOCK_EVENTS'].labels('any').inc()
                elif event['type'] == 'alert':
                    current_app.metrics['ALERTS_COUNT'].labels('warning', 'threshold').inc()
        except Exception:
            pass


sse_broker = SseBroker()

# Global metrics singletons (avoid duplicate registration on reload)
REQUEST_COUNT = None
REQUEST_LATENCY = None
STOCK_EVENTS = None
ALERTS_COUNT = None


def create_app() -> Flask:
    # Load .env first (for local dev)
    load_dotenv()
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Configuration
    app.config.from_object("app.config.Config")

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # Blueprints / routes
    from .auth import auth_bp
    from .routes import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # Prometheus metrics (create once)
    global REQUEST_COUNT, REQUEST_LATENCY, STOCK_EVENTS, ALERTS_COUNT
    if REQUEST_COUNT is None:
        REQUEST_COUNT = Counter('flask_request_total', 'Total HTTP requests', ['method', 'endpoint', 'http_status'])
    if REQUEST_LATENCY is None:
        REQUEST_LATENCY = Histogram('flask_request_latency_seconds', 'Request latency', ['endpoint'])
    if STOCK_EVENTS is None:
        STOCK_EVENTS = Counter('stock_events_total', 'Stock events committed', ['source'])
    if ALERTS_COUNT is None:
        ALERTS_COUNT = Counter('alerts_total', 'Alerts created', ['level', 'type'])

    @app.before_request
    def _metrics_before():
        try:
            request._prom_cm = REQUEST_LATENCY.labels(request.endpoint or 'unknown').time()
        except Exception:
            request._prom_cm = None

    @app.after_request
    def _metrics_after(resp):
        try:
            REQUEST_COUNT.labels(request.method, request.path, resp.status_code).inc()
            cm = getattr(request, '_prom_cm', None)
            if cm:
                cm.__exit__(None, None, None)
        except Exception:
            pass
        return resp

    @app.route('/metrics')
    def metrics():
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    # Expose counters to other modules
    app.metrics = {
        'STOCK_EVENTS': STOCK_EVENTS,
        'ALERTS_COUNT': ALERTS_COUNT,
    }

    # DB create on first run
    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

    return app


