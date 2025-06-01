#!/bin/python
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_marshmallow import Marshmallow
import os
import logging
import sys
import redis # Added for Redis

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()
login_manager = LoginManager()
bcrypt = Bcrypt()
ma = Marshmallow()
# Global Redis client instance, to be initialized in create_app
# This makes it accessible, e.g., for the session store.
redis_client = None

module_logger = logging.getLogger(__name__)

def load_user_from_id(user_id):
    from app.models import User
    return User.query.get(int(user_id))

login_manager.user_loader(load_user_from_id)
login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"

def setup_logging(app_name="app"):
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(level=log_level, format="[%(asctime)s] %(levelname)s in %(module)s.%(funcName)s: %(message)s")
    initial_logger = logging.getLogger(app_name)
    initial_logger.info(f"Logging configured at level {log_level_str}")

def create_app():
    global redis_client # To assign to the global instance

    setup_logging(__name__)
    app = Flask(__name__)

    # --- Critical Configurations from Environment ---
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    if not app.config["SECRET_KEY"]:
        module_logger.error("FATAL: SECRET_KEY environment variable is not set.")
        sys.exit("SECRET_KEY environment variable is not set. Application cannot start.")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        module_logger.error("FATAL: DATABASE_URL environment variable is not set.")
        sys.exit("DATABASE_URL environment variable is not set. Application cannot start.")

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- Redis Configuration ---
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        module_logger.error("FATAL: REDIS_URL environment variable is not set.")
        sys.exit("REDIS_URL environment variable is not set. Application cannot start (needed for session store).")
    app.config["REDIS_URL"] = redis_url

    try:
        # Initialize Redis client. `from_url` is convenient.
        # Health check can be done here too.
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True) # decode_responses=True for strings
        redis_client.ping() # Check connection
        module_logger.info(f"Successfully connected to Redis at {redis_url}")
    except redis.exceptions.ConnectionError as e:
        module_logger.error(f"FATAL: Could not connect to Redis at {redis_url}. Error: {e}")
        sys.exit(f"Could not connect to Redis. Application cannot start. Error: {e}")
    # ---------------------------


    db.init_app(app)
    migrate.init_app(app, db)
    # For SocketIO, if using Redis for its message queue (optional, separate from session store):
    # socketio.init_app(app, message_queue=app.config["REDIS_URL"], cors_allowed_origins="*", logger=True, engineio_logger=True)
    # For now, only using Redis for our custom session store, SocketIO uses its default internal queue.
    socketio.init_app(app, cors_allowed_origins="*", logger=True, engineio_logger=True)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    ma.init_app(app)

    from . import models
    # Import and register blueprints (order might matter for dependencies like shared_session_store)
    # If session_store.py needs redis_client from app, it must be initialized before session_store is imported by blueprints.
    # This is why redis_client is global in this module and session_store.py will import it.

    from .routes import bp as main_bp; app.register_blueprint(main_bp)
    from .blueprints.auth import bp as auth_bp; app.register_blueprint(auth_bp, url_prefix="/auth")
    from .blueprints.tenants import bp as tenants_bp; app.register_blueprint(tenants_bp, url_prefix="/api/tenants")
    from .blueprints.device_management import bp as device_bp; app.register_blueprint(device_bp, url_prefix="/api/devices")

    # screen_mirroring blueprint imports shared_session_store from utils.session_store
    # utils.session_store will need to import redis_client from app (this file)
    from .blueprints.screen_mirroring import bp as mirroring_bp
    app.register_blueprint(mirroring_bp, url_prefix="/api/mirroring")
    from .blueprints.screen_mirroring import events # Import events

    from .blueprints.batch_tasks import bp as batch_tasks_bp; app.register_blueprint(batch_tasks_bp, url_prefix="/api/tasks")
    from .blueprints.dynamic_data import bp as dynamic_data_bp; app.register_blueprint(dynamic_data_bp, url_prefix="/api/data")
    from .blueprints.monitoring import bp as monitoring_bp; app.register_blueprint(monitoring_bp, url_prefix="/api/monitoring")

    app.logger.info("Flask App created and blueprints registered.")
    return app
