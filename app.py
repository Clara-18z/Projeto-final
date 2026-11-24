from flask import Flask, current_app, render_template
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from config import Config
from database import db
from database.models import Permissao, Usuario
from services.permissions import (
    PERMISSION_DEFINITIONS,
    has_permission,
    permissions_for_profile,
)

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"
socketio = SocketIO()
migrate = Migrate()
csrf = CSRFProtect()


@login_manager.user_loader
def load_user(user_id):
    if user_id is None:
        return None
    return Usuario.query.get(int(user_id))


def seed_default_admin_user():
    permissions = []
    for code, name in PERMISSION_DEFINITIONS:
        permission = Permissao.query.filter_by(codigo=code).first()
        if permission is None:
            permission = Permissao(codigo=code, nome=name, descricao=name)
            db.session.add(permission)
        permissions.append(permission)

    db.session.flush()
    admin_permission_codes = permissions_for_profile("administrador")

    admin_user = Usuario.query.filter_by(username="admin").first()
    if admin_user is None:
        admin_user = Usuario(
            nome_completo="Administrador Master",
            email="admin@clinicanexo.com",
            username="admin",
            senha_hash=generate_password_hash(current_app.config["ADMIN_INITIAL_PASSWORD"]),
            perfil="administrador",
            ativo=True,
        )
        db.session.add(admin_user)
        db.session.flush()

    admin_user.email = admin_user.email or "admin@clinicanexo.com"
    for permission in permissions:
        if (
            permission.codigo in admin_permission_codes
            and permission not in admin_user.permissoes
        ):
            admin_user.permissoes.append(permission)
    for existing_admin in Usuario.query.filter_by(perfil="administrador").all():
        existing_admin.permissoes = [
            permission
            for permission in existing_admin.permissoes
            if permission.codigo in admin_permission_codes
        ]
    db.session.commit()


def ensure_medico_room_assignment_schema(engine=None):
    if engine is None:
        engine = db.engine
    inspector = inspect(engine)
    medico_columns = {column["name"] for column in inspector.get_columns("medicos")}
    if "sala_id" not in medico_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE medicos "
                    "ADD COLUMN sala_id INTEGER REFERENCES salas(id)"
                )
            )

    room_assignment_index = next(
        index
        for index in db.metadata.tables["medicos"].indexes
        if index.name == "uq_medicos_sala_id"
    )
    room_assignment_index.create(bind=engine, checkfirst=True)


def ensure_medico_presence_schema(engine=None):
    if engine is None:
        engine = db.engine
    inspector = inspect(engine)
    medico_columns = {column["name"] for column in inspector.get_columns("medicos")}
    if "presenca_ativa" not in medico_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE medicos "
                    "ADD COLUMN presenca_ativa BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )


def ensure_priority_approval_reference_schema(engine=None):
    if engine is None:
        engine = db.engine
    inspector = inspect(engine)
    policy_columns = {
        column["name"]
        for column in inspector.get_columns("politica_prioridade")
    }
    if "referencia_aprovacao" not in policy_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE politica_prioridade "
                    "ADD COLUMN referencia_aprovacao VARCHAR(100)"
                )
            )


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if app.config["APP_ENV"] == "production":
        if not app.config.get("SECRET_KEY"):
            raise RuntimeError("SECRET_KEY must be configured in production.")
        if not app.config.get("ADMIN_INITIAL_PASSWORD"):
            raise RuntimeError("ADMIN_INITIAL_PASSWORD must be configured in production.")
        app.config["DEBUG"] = False
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["REMEMBER_COOKIE_SECURE"] = True
    else:
        if not app.config.get("SECRET_KEY"):
            app.config["SECRET_KEY"] = "dev-secret-key-clinica-nexo"
        if not app.config.get("ADMIN_INITIAL_PASSWORD"):
            app.config["ADMIN_INITIAL_PASSWORD"] = "Admin@123"

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    socketio.init_app(app, async_mode="threading")
    csrf.init_app(app)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.context_processor
    def inject_access_helpers():
        return {
            "has_permission": lambda code: (
                current_user.is_authenticated and has_permission(current_user, code)
            )
        }

    from database import models  # noqa: F401
    from routes.auth import auth_bp
    from routes.agenda import agenda_bp
    from routes.auditoria import auditoria_bp
    from routes.atendimento import atendimento_bp
    from routes.fila import fila_bp
    from routes.clinica import clinica_bp
    from routes.financeiro import financeiro_bp
    from routes.pacientes import pacientes_bp
    from routes.relatorios import relatorios_bp
    from routes.servicos import servicos_bp
    from routes.solicitacoes import solicitacoes_bp
    from routes.usuarios import usuarios_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(agenda_bp)
    app.register_blueprint(auditoria_bp)
    app.register_blueprint(atendimento_bp)
    app.register_blueprint(fila_bp)
    app.register_blueprint(usuarios_bp)
    app.register_blueprint(pacientes_bp)
    app.register_blueprint(relatorios_bp)
    app.register_blueprint(clinica_bp)
    app.register_blueprint(financeiro_bp)
    app.register_blueprint(servicos_bp)
    app.register_blueprint(solicitacoes_bp)

    with app.app_context():
        db.create_all()
        ensure_medico_room_assignment_schema()
        ensure_medico_presence_schema()
        ensure_priority_approval_reference_schema()
        seed_default_admin_user()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health")
    def health():
        return {"status": "ok"}

    @app.route("/ready")
    def readiness():
        try:
            db.session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            current_app.logger.exception("Database readiness check failed.")
            return {"status": "unavailable"}, 503
        return {"status": "ready"}

    return app


app = create_app()


if __name__ == "__main__":
    if app.config["APP_ENV"] == "production":
        from waitress import serve

        serve(app, host=app.config["HOST"], port=app.config["PORT"])
    else:
        socketio.run(
            app,
            debug=app.config["DEBUG"],
            host=app.config["HOST"],
            port=app.config["PORT"],
        )
