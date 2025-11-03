from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import db
from .models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def role_required(role: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if current_user.role != role:
                flash("Acesso negado: requer papel de %s" % role, "error")
                return redirect(url_for("main.dashboard"))
            return fn(*args, **kwargs)

        return wrapper

    return decorator


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("main.dashboard"))
        flash("Credenciais inválidas", "error")
    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
@login_required
@role_required("admin")
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")
        if not email or not password:
            flash("Informe email e senha", "error")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("Email já cadastrado", "error")
            return render_template("register.html")
        User.create_user(email=email, password=password, role=role)
        flash("Usuário criado", "success")
        return redirect(url_for("main.users"))
    return render_template("register.html")


