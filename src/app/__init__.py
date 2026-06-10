"""Flask application factory and initialization."""
import os
from flask import Flask
from .config import config
from .models.base import db
from .logging_config import configure_logging


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application.

    Uses the application factory pattern for flexibility in testing
    and deployment scenarios.

    Args:
        config_name: Configuration to use ('development', 'testing', 'production').
                    Defaults to FLASK_ENV environment variable or 'development'.

    Returns:
        Configured Flask application instance.
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Configure logging before other initialization
    configure_logging(app)

    # Initialize extensions
    db.init_app(app)

    # Initialize Flask-Migrate
    from flask_migrate import Migrate
    Migrate(app, db)

    # Register error handlers
    from .errors import register_error_handlers
    register_error_handlers(app)

    # Register blueprints
    from .views import register_blueprints
    register_blueprints(app)

    # Expose Vite asset resolution to templates (production/static mode).
    from .vite_manifest import load_vite_assets

    @app.context_processor
    def inject_vite_assets():  # type: ignore[no-untyped-def]
        return {'vite_assets': lambda: load_vite_assets(app.static_folder)}

    return app
