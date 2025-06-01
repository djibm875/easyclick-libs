#!/bin/python
from flask import request, jsonify
from app import db
from app.models import Tenant, User # Make sure User is imported if used for current_user checks
from flask_login import login_required, current_user
from functools import wraps
from . import bp
from datetime import datetime, timezone # Added import

# Decorator for super_admin routes
def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "super_admin":
            return jsonify({"error": "Super admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

# Decorator for tenant_admin or super_admin
def tenant_admin_or_super_admin_required(f):
    @wraps(f)
    def decorated_function(tenant_id, *args, **kwargs): # tenant_id must be passed to decorator or function
        if not current_user.is_authenticated: return jsonify({"error": "Login required"}), 401
        if current_user.role == "super_admin": return f(tenant_id, *args, **kwargs)
        if current_user.role == "tenant_admin" and current_user.tenant_id == tenant_id : return f(tenant_id, *args, **kwargs)
        return jsonify({"error": "Tenant admin or super admin access required for this tenant"}), 403
    return decorated_function


@bp.route("/", methods=["POST"])
@login_required
@super_admin_required
def create_tenant():
    data = request.get_json(); name = data.get("name")
    if not name: return jsonify({"error": "Missing tenant name"}), 400
    if Tenant.query.filter_by(name=name).first(): return jsonify({"error": "Tenant name already exists"}), 409
    try:
        tenant = Tenant(name=name); db.session.add(tenant); db.session.commit()
        return jsonify(tenant.to_dict()), 201
    except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500

@bp.route("/", methods=["GET"])
@login_required
def list_tenants_or_own(): # Modified to allow non-superadmins to see their own tenant
    if current_user.role == "super_admin":
        tenants = Tenant.query.all()
        return jsonify([t.to_dict() for t in tenants]), 200
    elif current_user.tenant:
        return jsonify([current_user.tenant.to_dict()]), 200
    return jsonify([]), 200


@bp.route("/<int:tenant_id>", methods=["GET"])
@login_required
def get_tenant(tenant_id):
    if current_user.role != "super_admin" and current_user.tenant_id != tenant_id:
        return jsonify({"error": "Access denied"}), 403
    tenant = Tenant.query.get_or_404(tenant_id)
    return jsonify(tenant.to_dict()), 200

@bp.route("/<int:tenant_id>", methods=["PUT"])
@login_required
#@tenant_admin_or_super_admin_required # Apply this decorator if you modify it to take tenant_id
def update_tenant(tenant_id): # tenant_id passed from URL
    # Manual check for permission
    if not current_user.is_authenticated: return jsonify({"error": "Login required"}), 401
    is_super = current_user.role == "super_admin"
    is_tenant_admin_for_this_tenant = current_user.role == "tenant_admin" and current_user.tenant_id == tenant_id
    if not (is_super or is_tenant_admin_for_this_tenant):
        return jsonify({"error": "Access denied or insufficient permissions"}), 403

    tenant = Tenant.query.get_or_404(tenant_id)
    data = request.get_json(); name = data.get("name")
    if name and name != tenant.name:
        if Tenant.query.filter(Tenant.name == name, Tenant.id != tenant_id).first():
             return jsonify({"error": "Tenant name already exists"}), 409
        tenant.name = name
    tenant.updated_at = datetime.now(timezone.utc)
    try:
        db.session.commit(); return jsonify(tenant.to_dict()), 200
    except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500


@bp.route("/<int:tenant_id>", methods=["DELETE"])
@login_required
@super_admin_required
def delete_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    # Add more robust deletion logic (e.g., check for associated resources)
    if User.query.filter_by(tenant_id=tenant_id).count() > 0 : # Example check
         return jsonify({"error": "Cannot delete tenant with associated users. Please reassign or delete them first."}), 400
    try:
        db.session.delete(tenant); db.session.commit()
        return jsonify({"message": "Tenant deleted successfully"}), 200
    except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500
