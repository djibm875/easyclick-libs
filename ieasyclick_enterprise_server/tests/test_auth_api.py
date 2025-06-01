#!/bin/python
import json
from app.models import User, Tenant
# from flask import url_for # If using url_for to generate URLs

def test_register_new_user(test_client, init_database, new_user_data):
    """Test user registration with valid data."""
    response = test_client.post("/auth/register", json=new_user_data)
    assert response.status_code == 201
    data = response.json
    assert data["username"] == new_user_data["username"]
    assert "id" in data

    # Check if user and tenant are in the database
    user = User.query.filter_by(username=new_user_data["username"]).first()
    assert user is not None
    assert user.email == new_user_data["email"]
    tenant = Tenant.query.filter_by(name=new_user_data["tenant_name"]).first()
    assert tenant is not None
    assert user.tenant_id == tenant.id

def test_register_existing_username(test_client, init_database, new_user_data):
    """Test registration with an already existing username."""
    # First, register the user
    test_client.post("/auth/register", json=new_user_data)

    # Try to register again with the same username
    response_again = test_client.post("/auth/register", json={
        **new_user_data,
        "email": "another@example.com" # Different email
    })
    assert response_again.status_code == 409
    assert "Username already exists" in response_again.json["error"]

def test_register_existing_email(test_client, init_database, new_user_data):
    """Test registration with an already existing email."""
    test_client.post("/auth/register", json=new_user_data)
    response_again = test_client.post("/auth/register", json={
        **new_user_data,
        "username": "anotheruser" # Different username
    })
    assert response_again.status_code == 409
    assert "Email already exists" in response_again.json["error"]

def test_login_successful(test_client, init_database, new_user_data):
    """Test successful login with valid credentials."""
    # Register user first
    test_client.post("/auth/register", json=new_user_data)

    # Login
    login_response = test_client.post("/auth/login", json={
        "username": new_user_data["username"],
        "password": new_user_data["password"]
    })
    assert login_response.status_code == 200
    assert "Login successful" in login_response.json["message"]
    assert "user" in login_response.json
    assert login_response.json["user"]["username"] == new_user_data["username"]
    # Check for session cookie (implementation specific, but often `session` or `login_user` sets it)
    # For Flask-Login, the session cookie is HttpOnly, so not directly inspectable in JS.
    # The fact that subsequent @login_required routes work is an indicator.

def test_login_invalid_username(test_client, init_database, new_user_data):
    """Test login with a non-existent username."""
    test_client.post("/auth/register", json=new_user_data) # Register a user
    login_response = test_client.post("/auth/login", json={
        "username": "wronguser",
        "password": new_user_data["password"]
    })
    assert login_response.status_code == 401
    assert "Invalid username or password" in login_response.json["error"]

def test_login_invalid_password(test_client, init_database, new_user_data):
    """Test login with an incorrect password."""
    test_client.post("/auth/register", json=new_user_data)
    login_response = test_client.post("/auth/login", json={
        "username": new_user_data["username"],
        "password": "wrongpassword"
    })
    assert login_response.status_code == 401
    assert "Invalid username or password" in login_response.json["error"]

def test_logout(test_client, init_database, new_user_data):
    """Test user logout."""
    # Register and login user
    test_client.post("/auth/register", json=new_user_data)
    test_client.post("/auth/login", json={
        "username": new_user_data["username"],
        "password": new_user_data["password"]
    })

    # Logout
    logout_response = test_client.post("/auth/logout") # No JSON body needed usually
    assert logout_response.status_code == 200
    assert "Logout successful" in logout_response.json["message"]

    # Verify user is logged out by accessing a protected route (e.g., /auth/status)
    status_response = test_client.get("/auth/status")
    # Flask-Login typically redirects to login_view or returns 401 if not AJAX
    # Since our login_view is "auth.login", and it is not configured for AJAX unauthorized response,
    # it might redirect to HTML. Let's assume for API it should be 401 if not logged in.
    # This depends on how Flask-Login handles unauthorized API requests vs browser requests.
    # If login_manager.unauthorized() is default, it redirects.
    # For APIs, it is better to return 401. This might require custom unauthorized handler.
    # For now, let's check if the status code is not 200.
    assert status_response.status_code == 401 # Expecting 401 if @login_required and not logged in for an API

def test_status_authenticated(test_client, init_database, new_user_data):
    """Test /auth/status for an authenticated user."""
    test_client.post("/auth/register", json=new_user_data)
    test_client.post("/auth/login", json={
        "username": new_user_data["username"],
        "password": new_user_data["password"]
    })

    status_response = test_client.get("/auth/status")
    assert status_response.status_code == 200
    assert status_response.json["user"]["username"] == new_user_data["username"]

def test_status_unauthenticated(test_client, init_database):
    """Test /auth/status for an unauthenticated user."""
    status_response = test_client.get("/auth/status")
    assert status_response.status_code == 401 # Expecting 401 as per @login_required

# To make Flask-Login return 401 for unauthorized API requests instead of redirecting:
# Update in app/__init__.py, inside create_app():
# @login_manager.unauthorized_handler
# def unauthorized():
#     # Check if the request is likely an API request
#     if request.blueprint and request.blueprint.startswith("api"): # Or check accept headers
#         return jsonify(message="Authentication required."), 401
#     return redirect(url_for("auth.login")) # Default redirect for browser
