import os
from datetime import datetime
import click
from flask import Flask

from app import create_app, db
from app.models import User, Material, Price, StockEvent


app = create_app()


@app.cli.command("init-db")
def init_db_command():
    """Initialize the database (drop + create tables)."""
    from app import db
    click.echo("Initializing database...")
    db.drop_all()
    db.create_all()
    click.echo("Database initialized.")


@app.cli.command("seed-demo")
def seed_demo_command():
    """Seed demo data: users, materials, initial prices."""
    click.echo("Seeding demo data...")

    if not User.query.filter_by(email="admin@local").first():
        User.create_user(email="admin@local", password="Admin123!", role="admin")
    if not User.query.filter_by(email="user@local").first():
        User.create_user(email="user@local", password="User123!", role="user")

    demo_materials = [
        {"name": "Capacete EPI", "category": "EPI", "unit": "un"},
        {"name": "Luva de Proteção", "category": "EPI", "unit": "par"},
        {"name": "Óculos de Proteção", "category": "EPI", "unit": "un"},
        {"name": "Cobre (barra)", "category": "metal", "unit": "kg"},
        {"name": "Alumínio (lingote)", "category": "metal", "unit": "kg"},
        {"name": "Latão", "category": "metal", "unit": "kg"},
    ]

    for m in demo_materials:
        material = Material.query.filter_by(name=m["name"]).first()
        if not material:
            material = Material(name=m["name"], category=m["category"], unit=m["unit"])
            db.session.add(material)
            db.session.flush()

        if not Price.query.filter_by(material_id=material.id).first():
            db.session.add(Price(material_id=material.id, value=100.0))

    db.session.commit()
    click.echo("Demo data seeded.")


@app.cli.command("run")
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=5000, type=int)
def run_server(host, port):
    """Run the development server and start the simulator."""
    from app.iot_simulator import start_simulator
    from app.mqtt_client import start_mqtt

    start_simulator(app)

    start_mqtt(app)
    app.run(host=host, port=port, debug=True)


if __name__ == "__main__":

    cli = click.Group(commands=app.cli.commands)
    cli()


