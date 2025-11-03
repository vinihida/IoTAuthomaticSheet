import json
import random
from datetime import datetime, timedelta
from typing import Dict

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask_login import login_required, current_user
from sqlalchemy import func

from . import db, sse_broker
from .auth import role_required
from .models import Material, Price, StockEvent, User, MaterialPolicy, Alert
import math
import requests


main_bp = Blueprint("main", __name__)


def _current_stock(material_id: int) -> float:
    total = (
        db.session.query(func.coalesce(func.sum(StockEvent.qty), 0.0))
        .filter_by(material_id=material_id)
        .scalar()
        or 0.0
    )
    return float(total)


def _latest_price(material_id: int) -> float:
    p = (
        Price.query.filter_by(material_id=material_id)
        .order_by(Price.created_at.desc())
        .first()
    )
    return float(p.value) if p else 0.0


def _policy_for(material: Material) -> MaterialPolicy:
    pol = MaterialPolicy.query.filter_by(material_id=material.id).first()
    if not pol:
        pol = MaterialPolicy(
            material_id=material.id,
            min_stock_threshold=0.0,
            max_remove_percent=80.0,
            max_qty_per_op=1000.0 if material.unit != "kg" else 100.0,
            max_qty_per_day=5000.0,
            require_integer_units=(material.unit != "kg"),
        )
        db.session.add(pol)
        db.session.commit()
    return pol


@main_bp.route("/")
@login_required
def dashboard():
    materials = Material.query.order_by(Material.category, Material.name).all()
    rows = []
    for m in materials:
        rows.append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "unit": m.unit,
                "stock": _current_stock(m.id),
                "price": _latest_price(m.id),
            }
        )
    return render_template("dashboard.html", rows=rows, user=current_user)


@main_bp.route("/users")
@login_required
@role_required("admin")
def users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users.html", users=users)


@main_bp.route("/materials", methods=["GET", "POST"])
@login_required
@role_required("admin")
def materials():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "EPI").strip()
        unit = request.form.get("unit", "un").strip()
        price = float(request.form.get("price", "0") or 0)
        if not name:
            flash("Informe o nome do material", "error")
        else:
            m = Material(name=name, category=category, unit=unit)
            db.session.add(m)
            db.session.flush()
            db.session.add(Price(material_id=m.id, value=price))
            db.session.commit()
            flash("Material criado", "success")
            sse_broker.publish({"type": "material_created"})
        return redirect(url_for("main.materials"))

    mats = Material.query.order_by(Material.category, Material.name).all()
    return render_template("materials.html", materials=mats)
@main_bp.route("/materials/<int:mid>/policy", methods=["GET", "POST"])
@login_required
@role_required("admin")
def policies(mid: int):
    m = Material.query.get_or_404(mid)
    pol = _policy_for(m)
    if request.method == "POST":
        pol.min_stock_threshold = float(request.form.get("min_stock_threshold", pol.min_stock_threshold))
        pol.max_remove_percent = float(request.form.get("max_remove_percent", pol.max_remove_percent))
        pol.max_qty_per_op = float(request.form.get("max_qty_per_op", pol.max_qty_per_op))
        pol.max_qty_per_day = float(request.form.get("max_qty_per_day", pol.max_qty_per_day))
        pol.require_integer_units = request.form.get("require_integer_units") == "on"
        db.session.commit()
        flash("Política atualizada", "success")
        return redirect(url_for("main.policies", mid=mid))
    return render_template("policy.html", m=m, pol=pol)

@main_bp.route("/alerts")
@login_required
@role_required("admin")
def alerts():
    alerts = Alert.query.order_by(Alert.created_at.desc()).limit(200).all()
    return render_template("alerts.html", alerts=alerts)

@main_bp.route("/alerts/<int:aid>/resolve", methods=["POST"])
@login_required
@role_required("admin")
def resolve_alert(aid: int):
    a = Alert.query.get_or_404(aid)
    a.resolved = True
    db.session.commit()
    flash("Alerta resolvido", "success")
    return redirect(url_for("main.alerts"))


@main_bp.route("/materials/<int:mid>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_material(mid: int):
    m = Material.query.get_or_404(mid)
    db.session.delete(m)
    db.session.commit()
    flash("Material removido", "success")
    sse_broker.publish({"type": "material_deleted"})
    return redirect(url_for("main.materials"))


def _validate_qty(material: Material, qty: float, removing: bool) -> str | None:
    """Return error message if invalid, otherwise None."""
    if qty <= 0:
        return "Quantidade deve ser positiva"
    pol = _policy_for(material)
    # integer rule
    if pol.require_integer_units:
        if abs(qty - round(qty)) > 1e-9:
            return "Para este item, a quantidade deve ser inteira"
    # per-operation cap
    if qty > pol.max_qty_per_op:
        return "Quantidade excede o limite por operação"

    if removing:
        current = _current_stock(material.id)
        if qty > current:
            return "Estoque insuficiente"
        if current > 0 and qty > (pol.max_remove_percent / 100.0) * current:
            return "Não é permitido remover além do limite percentual configurado"
        # daily limit (removals)
        from datetime import date
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(day=day_start.day + 1) if day_start.day < 28 else day_start + timedelta(days=1)
        removed_today = (
            db.session.query(func.coalesce(func.sum(func.abs(StockEvent.qty)), 0.0))
            .filter(StockEvent.material_id == material.id, StockEvent.qty < 0)
            .filter(StockEvent.created_at >= day_start, StockEvent.created_at < day_end)
            .scalar()
            or 0.0
        )
        if removed_today + qty > pol.max_qty_per_day:
            return "Limite diário de remoções atingido para este item"
    return None


def _anomaly_check(material: Material, qty: float) -> str | None:
    if not material:
        return None
    if not current_app.config.get("ENABLE_ANOMALY_GUARD", True):
        return None
    window = int(current_app.config.get("ANOMALY_WINDOW", 50))
    zcut = float(current_app.config.get("ANOMALY_ZSCORE", 3.0))
    # Use past removals (absolute quantities)
    events = (
        StockEvent.query.filter(StockEvent.material_id == material.id, StockEvent.qty < 0)
        .order_by(StockEvent.created_at.desc())
        .limit(window)
        .all()
    )
    vals = [abs(e.qty) for e in events if abs(e.qty) > 0]
    if len(vals) < 10:
        return None
    mean = sum(vals) / len(vals)
    import math
    var = sum((v - mean) ** 2 for v in vals) / max(1, (len(vals) - 1))
    std = math.sqrt(var)
    if std == 0:
        return None
    z = (qty - mean) / std
    if z > zcut:
        # Log alert
        db.session.add(
            Alert(
                level="critical",
                type="anomaly",
                message=f"Remoção anômala detectada: {qty:.2f} {material.unit} em {material.name} (z={z:.2f})",
                material_id=material.id,
            )
        )
        db.session.commit()
        return "Remoção anômala detectada; operação bloqueada. Contate o admin."
    return None


@main_bp.route("/stock/add", methods=["POST"])
@login_required
def stock_add():
    material_id = int(request.form.get("material_id"))
    qty = float(request.form.get("qty", "0") or 0)
    material = Material.query.get_or_404(material_id)
    err = _validate_qty(material, qty, removing=False)
    if err:
        flash(err, "error")
        return redirect(url_for("main.dashboard"))
    price = _latest_price(material_id)
    qty = round(qty, 2)
    event = StockEvent(material_id=material_id, qty=qty, price_at_event=price, source="manual")
    db.session.add(event)
    db.session.commit()
    sse_broker.publish({"type": "stock", "material_id": material_id})
    # Threshold alert for low stock
    pol = _policy_for(material)
    if _current_stock(material_id) < pol.min_stock_threshold:
        db.session.add(Alert(level="warning", type="threshold", message=f"Estoque baixo: {material.name}", material_id=material_id))
        db.session.commit()
        sse_broker.publish({"type": "alert"})
    return redirect(url_for("main.dashboard"))


@main_bp.route("/stock/remove", methods=["POST"])
@login_required
def stock_remove():
    material_id = int(request.form.get("material_id"))
    qty = float(request.form.get("qty", "0") or 0)
    material = Material.query.get_or_404(material_id)
    err = _validate_qty(material, qty, removing=True) or _anomaly_check(material, qty)
    if err:
        flash(err, "error")
        return redirect(url_for("main.dashboard"))
    price = _latest_price(material_id)
    qty = round(qty, 2)
    event = StockEvent(material_id=material_id, qty=-qty, price_at_event=price, source="manual")
    db.session.add(event)
    db.session.commit()
    sse_broker.publish({"type": "stock", "material_id": material_id})
    # Threshold alert for low stock after removal
    pol = _policy_for(material)
    if _current_stock(material_id) < pol.min_stock_threshold:
        db.session.add(Alert(level="warning", type="threshold", message=f"Estoque baixo: {material.name}", material_id=material_id))
        db.session.commit()
        sse_broker.publish({"type": "alert"})
    return redirect(url_for("main.dashboard"))


@main_bp.route("/sse")
@login_required
def sse_stream():
    q = sse_broker.register()

    def event_stream():
        try:
            while True:
                data: Dict = q.get()
                yield f"data: {json.dumps(data)}\n\n"
        finally:
            sse_broker.unregister(q)

    headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
    return Response(stream_with_context(event_stream()), headers=headers)


def _month_bounds(ym: str | None) -> tuple[datetime, datetime]:
    """Return (start, end) for given YYYY-MM or current month if None/invalid."""
    if ym:
        try:
            year, month = ym.split("-")
            start = datetime(int(year), int(month), 1)
        except Exception:
            start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


@main_bp.route("/reports")
@login_required
@role_required("admin")
def reports():
    ym = request.args.get("ym")  # YYYY-MM
    start, end = _month_bounds(ym)

    rows = (
        db.session.query(
            Material.category,
            Material.name,
            func.sum(func.abs(StockEvent.qty) * StockEvent.price_at_event),
        )
        .join(Material, Material.id == StockEvent.material_id)
        .filter(StockEvent.qty < 0)
        .filter(StockEvent.created_at >= start, StockEvent.created_at < end)
        .group_by(Material.category, Material.name)
        .order_by(Material.category, Material.name)
        .all()
    )

    total = sum(r[2] or 0 for r in rows)
    return render_template("reports.html", rows=rows, total=total, start=start, end=end)


@main_bp.route("/reports.csv")
@login_required
@role_required("admin")
def reports_csv():
    ym = request.args.get("ym")
    start, end = _month_bounds(ym)

    rows = (
        db.session.query(
            Material.category,
            Material.name,
            func.sum(func.abs(StockEvent.qty) * StockEvent.price_at_event),
        )
        .join(Material, Material.id == StockEvent.material_id)
        .filter(StockEvent.qty < 0)
        .filter(StockEvent.created_at >= start, StockEvent.created_at < end)
        .group_by(Material.category, Material.name)
        .order_by(Material.category, Material.name)
        .all()
    )

    def generate():
        yield "categoria,item,valor\n"
        for cat, name, value in rows:
            yield f"{cat},{name},{(value or 0):.2f}\n"

    headers = {
        "Content-Type": "text/csv",
        "Content-Disposition": f"attachment; filename=relatorio_{start.strftime('%Y-%m')}.csv",
    }
    return Response(generate(), headers=headers)


@main_bp.route("/analytics")
@login_required
@role_required("admin")
def analytics():
    # Simple monthly consumption average over last 3 months; suggest reorder when stock < avg
    suggestions = []
    materials = Material.query.order_by(Material.name).all()
    for m in materials:
        # last 90 days removals
        start = datetime.utcnow() - timedelta(days=90)
        removes = (
            db.session.query(func.abs(func.sum(StockEvent.qty)))
            .filter(StockEvent.material_id == m.id, StockEvent.qty < 0, StockEvent.created_at >= start)
            .scalar()
            or 0.0
        )
        monthly = removes / 3.0
        stock = _current_stock(m.id)
        pol = _policy_for(m)
        need = max(0.0, (monthly + pol.min_stock_threshold) - stock)
        if need > 0:
            suggestions.append({
                'material': m,
                'monthly': monthly,
                'stock': stock,
                'suggest_qty': round(need, 2),
            })
    return render_template("analytics.html", suggestions=suggestions)


@main_bp.route("/analytics/suggest/<int:mid>", methods=["POST"])
@login_required
@role_required("admin")
def analytics_suggest(mid: int):
    m = Material.query.get_or_404(mid)
    url = current_app.config.get('ERP_WEBHOOK_URL')
    payload = {
        'materialId': m.id,
        'materialName': m.name,
        'unit': m.unit,
        'ts': datetime.utcnow().isoformat() + 'Z',
    }
    if not url:
        db.session.add(Alert(level='info', type='policy', message=f"Sugestão ERP (mock): {m.name}", material_id=m.id))
        db.session.commit()
        flash("Sugestão enviada (mock)", "success")
        sse_broker.publish({"type": "alert"})
        return redirect(url_for('main.analytics'))
    try:
        requests.post(url, json=payload, timeout=5)
        flash("Sugestão enviada ao ERP", "success")
    except Exception:
        flash("Falha ao enviar ao ERP (ver logs)", "error")
    return redirect(url_for('main.analytics'))


