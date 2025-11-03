import json
import threading
import time
from typing import Optional

from flask import Flask, current_app

from . import db, sse_broker
from .models import Material, Price, StockEvent, Alert


_client = None
_thread: Optional[threading.Thread] = None
_running = False


def _safe_import_mqtt():
    try:
        import paho.mqtt.client as mqtt  # type: ignore
        return mqtt
    except Exception:  # pragma: no cover
        return None


def _handle_stock(material_id: int, qty: float, event_uuid: Optional[str], source: str) -> Optional[str]:
    # Import validation helpers lazily to avoid circular issues
    from .routes import _validate_qty, _anomaly_check, _latest_price, _current_stock, _policy_for

    m = Material.query.get(material_id)
    if not m:
        return "Material não encontrado"
    err = _validate_qty(m, abs(qty), removing=(qty < 0))
    if not err and qty < 0:
        err = _anomaly_check(m, abs(qty))
    if err:
        db.session.add(Alert(level="warning", type="policy", message=f"MQTT bloqueado: {err}", material_id=material_id))
        db.session.commit()
        return err
    price = _latest_price(material_id)
    ev = StockEvent(
        material_id=material_id,
        qty=qty,
        price_at_event=price,
        source=source,
        event_uuid=event_uuid,
    )
    # idempotência
    if event_uuid and StockEvent.query.filter_by(event_uuid=event_uuid).first():
        return None
    db.session.add(ev)
    db.session.commit()
    sse_broker.publish({"type": "stock", "material_id": material_id})

    # alerta de threshold
    pol = _policy_for(m)
    if _current_stock(material_id) < pol.min_stock_threshold:
        db.session.add(Alert(level="warning", type="threshold", message=f"Estoque baixo: {m.name}", material_id=material_id))
        db.session.commit()
        sse_broker.publish({"type": "alert"})
    return None


def _handle_price(material_id: int, value: float) -> None:
    if value <= 0:
        return
    if not Material.query.get(material_id):
        return
    db.session.add(Price(material_id=material_id, value=float(f"{value:.2f}")))
    db.session.commit()
    sse_broker.publish({"type": "price", "material_id": material_id})


def start_mqtt(app: Flask) -> None:
    global _client, _thread, _running
    if not app.config.get("MQTT_ENABLED", False):
        return
    mqtt = _safe_import_mqtt()
    if mqtt is None:
        app.logger.warning("MQTT_ENABLED=1, mas paho-mqtt não está instalado. Ignorando.")
        return

    if _thread and _thread.is_alive():
        return

    def run():  # pragma: no cover
        nonlocal mqtt
        with app.app_context():
            try:
                client = mqtt.Client(client_id=app.config.get("MQTT_CLIENT_ID", "iot-sheet-client"), callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
                _authu = app.config.get("MQTT_USERNAME")
                _authp = app.config.get("MQTT_PASSWORD")
                if _authu and _authp:
                    client.username_pw_set(_authu, _authp)

                def on_connect(c, userdata, flags, reason_code, properties=None):
                    app.logger.info(f"MQTT conectado: {reason_code}")
                    # Subscriptions
                    c.subscribe("factory/stock/+/add")
                    c.subscribe("factory/stock/+/remove")
                    c.subscribe("factory/price/+/set")

                def on_message(c, userdata, msg):
                    try:
                        topic = msg.topic
                        payload = json.loads(msg.payload.decode("utf-8") or "{}")
                        parts = topic.split("/")
                        if len(parts) >= 4 and parts[0] == "factory":
                            kind, mat_id_str, action = parts[1], parts[2], parts[3]
                            material_id = int(mat_id_str)
                            if kind == "stock":
                                qty = float(payload.get("qty", 0))
                                eid = payload.get("eventId")
                                if action == "add":
                                    _handle_stock(material_id, abs(qty), eid, source="iot")
                                elif action == "remove":
                                    _handle_stock(material_id, -abs(qty), eid, source="iot")
                            elif kind == "price" and action == "set":
                                value = float(payload.get("value", 0))
                                _handle_price(material_id, value)
                    except Exception as e:
                        app.logger.warning(f"Erro ao processar mensagem MQTT: {e}")

                client.on_connect = on_connect
                client.on_message = on_message

                host = app.config.get("MQTT_BROKER")
                port = int(app.config.get("MQTT_PORT", 1883))
                try:
                    client.connect(host, port, keepalive=60)
                except Exception as e:
                    app.logger.warning(f"Não foi possível conectar ao broker MQTT ({host}:{port}): {e}")
                    return  # Saímos silenciosamente sem derrubar o app

                client.loop_start()
                while True:
                    time.sleep(2)
            except Exception as e:
                app.logger.warning(f"MQTT thread finalizada: {e}")

    _thread = threading.Thread(target=run, daemon=True)
    _thread.start()


