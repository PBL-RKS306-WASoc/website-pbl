import click
from flask import Flask, render_template_string
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .logging_setup import setup_logging


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    setup_logging(app)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models  # noqa: F401

    # Daftarkan blueprint auth, catalog, dan admin
    from .auth import bp as auth_bp
    from .catalog import bp as catalog_bp
    from .admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(admin_bp)

    # Perintah CLI untuk membuat akun admin pertama lewat terminal
    @app.cli.command("create-admin")
    @click.argument("username")
    @click.argument("email")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username, email, password):
        from .models import User
        if User.query.filter_by(username=username).first():
            click.echo(f"Username {username} sudah ada!")
            return
        admin = User(username=username, email=email, role="admin", full_name="Admin Toko")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Akun admin '{username}' berhasil dibuat!")

    return app