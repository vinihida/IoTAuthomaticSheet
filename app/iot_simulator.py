import random
import threading
import time
from typing import Optional

from flask import Flask
from sqlalchemy import func

from . import db, sse_broker
from .models import Material, Price, StockEvent


_sim_thread: Optional[threading.Thread] = None
_sim_running = False


def _jitter_price(material: Material) -> None:
    last_price = (
        Price.query.filter_by(material_id=material.id)
        .order_by(Price.created_at.desc())
        .first()
    )
    base = last_price.value if last_price else 100.0
    # +/- up to 5%
    new_price = max(0.01, base * (1 + random.uniform(-0.05, 0.05)))
    db.session.add(Price(material_id=material.id, value=float(f"{new_price:.2f}")))
    db.session.commit()
    sse_broker.publish({"type": "price", "material_id": material.id})


def _random_stock_event(material: Material) -> None:
    # Randomly add or remove small qty
    add = random.choice([True, False])
    qty = round(random.uniform(1, 10), 2)
    if material.unit == "kg":
        qty = round(random.uniform(0.5, 5.0), 2)

    # Ensure not to go negative when removing
    total = (
        db.session.query(func.coalesce(func.sum(StockEvent.qty), 0))
        .filter_by(material_id=material.id)
        .scalar()
        or 0
    )
    if not add and qty > float(total):
        add = True

    last_price = (
        Price.query.filter_by(material_id=material.id)
        .order_by(Price.created_at.desc())
        .first()
    )
    price = last_price.value if last_price else 100.0
    signed_qty = qty if add else -qty
    db.session.add(
        StockEvent(material_id=material.id, qty=signed_qty, price_at_event=price, source="simulator")
    )
    db.session.commit()
    sse_broker.publish({"type": "stock", "material_id": material.id})


def simulator_loop(app: Flask) -> None:
    global _sim_running
    with app.app_context():
        price_interval = int(app.config.get("SIM_PRICE_JITTER_SEC", 10))
        stock_interval = int(app.config.get("SIM_STOCK_EVENT_SEC", 8))
        last_price_tick = 0
        last_stock_tick = 0
        while _sim_running:
            now = time.time()
            # price updates
            if now - last_price_tick >= price_interval:
                for m in Material.query.all():
                    _jitter_price(m)
                last_price_tick = now
            # stock events
            if now - last_stock_tick >= stock_interval:
                mats = Material.query.all()
                if mats:
                    _random_stock_event(random.choice(mats))
                last_stock_tick = now
            time.sleep(1)


def start_simulator(app: Flask) -> None:
    global _sim_thread, _sim_running
    if _sim_thread and _sim_thread.is_alive():
        return
    _sim_running = True
    _sim_thread = threading.Thread(target=simulator_loop, args=(app,), daemon=True)
    _sim_thread.start()


def stop_simulator():
    global _sim_running
    _sim_running = False


