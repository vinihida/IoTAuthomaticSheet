from datetime import datetime
from typing import Optional

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")  # 'user' | 'admin'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def create_user(email: str, password: str, role: str = "user") -> "User":
        user = User(email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # 'EPI' | 'metal'
    unit = db.Column(db.String(20), nullable=False, default="un")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    prices = db.relationship("Price", backref="material", lazy=True, cascade="all, delete-orphan")
    events = db.relationship("StockEvent", backref="material", lazy=True, cascade="all, delete-orphan")


class Price(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"), nullable=False, index=True)
    value = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class StockEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"), nullable=False, index=True)
    qty = db.Column(db.Float, nullable=False)  # positive for add, negative for remove
    price_at_event = db.Column(db.Float, nullable=False)
    source = db.Column(db.String(50), nullable=False, default="manual")  # 'manual' | 'simulator' | 'iot'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    # Optional idempotency for IoT
    event_uuid = db.Column(db.String(64), unique=True, nullable=True)


class MaterialPolicy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"), unique=True, nullable=False)
    min_stock_threshold = db.Column(db.Float, nullable=False, default=0.0)
    max_remove_percent = db.Column(db.Float, nullable=False, default=80.0)  # percent of current stock
    max_qty_per_op = db.Column(db.Float, nullable=False, default=1000.0)
    max_qty_per_day = db.Column(db.Float, nullable=False, default=5000.0)
    require_integer_units = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(20), nullable=False, default="warning")  # info|warning|critical
    type = db.Column(db.String(50), nullable=False)  # policy|anomaly|threshold
    message = db.Column(db.String(500), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved = db.Column(db.Boolean, nullable=False, default=False)


