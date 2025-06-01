#!/bin/python
from flask import request, jsonify
from werkzeug.security import generate_password_hash # Already in models, but good for direct use
from app import db, bcrypt
from app.models import User, Tenant
from flask_login import login_user, logout_user, login_required, current_user
from . import bp

@bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("email") or not data.get("password") or not data.get("tenant_name"): # Assuming new tenants can be named here for simplicity, or provide tenant_id
        return jsonify({"error": "Missing required fields (username, email, password, tenant_name)"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already exists"}), 409
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already exists"}), 409

    # Find or create tenant
    tenant = Tenant.query.filter_by(name=data["tenant_name"]).first()
    if not tenant:
        # Option 1: Create tenant if it does not exist (if allowed)
        tenant = Tenant(name=data["tenant_name"])
        db.session.add(tenant)
        # Option 2: Reject if tenant must pre-exist (depends on business logic)
        # return jsonify({"error": "Tenant not found"}), 404

    try:
        user = User(
            username=data["username"],
            email=data["email"],
            role=data.get("role", "user"), # Default role
            tenant=tenant # Associate user with tenant
        )
        user.set_password(data["password"]) # Hashes password
        db.session.add(user)
        db.session.commit()
        login_user(user) # Log in after registration
        return jsonify(user.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Could not register user", "message": str(e)}), 500

@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"error": "Missing username or password"}), 400

    user = User.query.filter_by(username=data["username"]).first()
    if user and user.check_password(data["password"]):
        login_user(user, remember=data.get("remember", False))
        # Update last_seen for user if we add such a field
        return jsonify({"message": "Login successful", "user": user.to_dict()}), 200
    return jsonify({"error": "Invalid username or password"}), 401

@bp.route("/logout", methods=["POST"])
@login_required # Ensures user is logged in to log out
def logout():
    logout_user()
    return jsonify({"message": "Logout successful"}), 200

@bp.route("/status", methods=["GET"])
@login_required
def status():
    return jsonify({"user": current_user.to_dict()}), 200
