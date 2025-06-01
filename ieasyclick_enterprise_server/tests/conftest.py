#!/bin/python
import pytest
from app import create_app, db
from app.models import User, Tenant # Import models needed for setup/teardown

@pytest.fixture(scope="module")
def test_app():
    """Create and configure a new app instance for each test module."""
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", # Use in-memory SQLite for tests
        "WTF_CSRF_ENABLED": False, # Disable CSRF for simpler form testing if using Flask-WTF
        "LOGIN_DISABLED": False, # Ensure login is enabled for auth tests
        "SERVER_NAME": "localhost.localdomain" # Required for url_for outside of request context in some cases
    })

    with app.app_context():
        db.create_all() # Create database tables
        yield app # Provide the app object to tests
        db.session.remove()
        db.drop_all() # Clean up database tables after tests

@pytest.fixture(scope="module")
def test_client(test_app):
    """A test client for the app."""
    return test_app.test_client()

@pytest.fixture(scope="function") # Use function scope if db needs to be clean for each test
def init_database(test_app):
    """Fixture to ensure a clean database for each test function if needed."""
    with test_app.app_context():
        # db.drop_all() # Uncomment if you want to drop/recreate for every test
        # db.create_all()
        # Add any default data if necessary, e.g., a default tenant or super_admin
        # For now, let tests handle their own data setup after this initial create.
        yield db # Provide the db object
        # db.session.remove()
        # db.drop_all() # Clean up after each test function

@pytest.fixture(scope="function")
def new_user_data():
    """Provides data for a new user registration."""
    return {
        "username": "testuser",
        "email": "test@example.com",
        "password": "Testpassword123!",
        "tenant_name": "TestTenant"
    }
