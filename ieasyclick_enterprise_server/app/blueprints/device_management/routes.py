#!/bin/python
from flask import request, jsonify
from . import bp
from app.models import Device
from app import db
from datetime import datetime, timezone
from flask_login import login_required, current_user
import logging
from .schemas import DeviceRegistrationSchema, DeviceUpdateSchema # Added

logger = logging.getLogger(__name__)
device_registration_schema = DeviceRegistrationSchema() # Instantiate once
device_update_schema = DeviceUpdateSchema() # Instantiate once

@bp.route("/", methods=["GET"])
@login_required
def list_devices():
    # ... (existing code from previous step, no changes to this route for validation) ...
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 10, type=int)
        query = Device.query
        if current_user.role != "super_admin":
            query = query.filter(Device.tenant_id == current_user.tenant_id)
        status_filter = request.args.get("status")
        platform_filter = request.args.get("platform")
        if status_filter: query = query.filter(Device.status == status_filter)
        if platform_filter: query = query.filter(Device.platform == platform_filter)
        devices_pagination = query.order_by(Device.registered_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        devices = devices_pagination.items
        return jsonify({"devices": [device.to_dict() for device in devices],"total": devices_pagination.total, "pages": devices_pagination.pages, "current_page": devices_pagination.page}), 200
    except Exception as e:
        logger.error(f"Error listing devices: {e}", exc_info=True)
        return jsonify({"error": "Could not retrieve devices", "message": str(e)}), 500


@bp.route("/register", methods=["POST"])
@login_required
def register_device():
    json_data = request.get_json()
    if not json_data:
        return jsonify({"error": "Request body must be JSON"}), 400

    # Validate and deserialize request data
    try:
        loaded_data = device_registration_schema.load(json_data)
    except Exception as err: # Marshmallow raises ValidationError, but Exception catches other issues too.
        logger.warning(f"Device registration validation failed: {err.messages if hasattr(err, 'messages') else str(err)}")
        return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err, 'messages') else str(err)}), 400

    device_id_str = loaded_data["device_id"]
    platform = loaded_data["platform"]
    # Optional fields from loaded_data
    device_name = loaded_data.get("device_name")
    os_version = loaded_data.get("os_version")

    existing_device_globally = Device.query.filter_by(device_id=device_id_str).first()
    if existing_device_globally and existing_device_globally.tenant_id != current_user.tenant_id:
        logger.warning(f"Attempt to register device {device_id_str} by tenant {current_user.tenant_id}, but already registered to tenant {existing_device_globally.tenant_id}.")
        return jsonify({"error": f"Device {device_id_str} already registered to a different tenant."}), 409

    target_tenant_id = current_user.tenant_id
    if not target_tenant_id:
        logger.error(f"User {current_user.username} attempted to register device but has no tenant_id.")
        return jsonify({"error": "User not associated with a tenant. Cannot register device."}), 400

    device_to_update_or_create = existing_device_globally

    if device_to_update_or_create: # Update
        # For update, we can use the DeviceUpdateSchema or just update fields from loaded_data
        device_to_update_or_create.device_name = device_name if device_name is not None else device_to_update_or_create.device_name
        device_to_update_or_create.platform = platform # Platform is required in reg schema
        device_to_update_or_create.os_version = os_version if os_version is not None else device_to_update_or_create.os_version
        # device_to_update_or_create.status = loaded_data.get("status", "online") # If status was in schema
        device_to_update_or_create.status = "online" # Default on re-register/update
        device_to_update_or_create.last_seen = datetime.now(timezone.utc)
        try:
            db.session.commit()
            logger.info(f"Device {device_id_str} updated for tenant {target_tenant_id}.")
            return jsonify(device_to_update_or_create.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating device {device_id_str}: {e}", exc_info=True)
            return jsonify({"error": f"Failed to update existing device: {str(e)}"}), 500
    else: # Create new
        new_device = Device(
            device_id=device_id_str,
            device_name=device_name,
            platform=platform,
            os_version=os_version,
            status="online", # Default status
            last_seen=datetime.now(timezone.utc),
            registered_at=datetime.now(timezone.utc),
            tenant_id=target_tenant_id
        )
        new_device.generate_api_key()
        try:
            db.session.add(new_device)
            db.session.commit()
            logger.info(f"New device {device_id_str} registered for tenant {target_tenant_id} with API key.")
            return jsonify(new_device.to_dict_with_key()), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error registering new device {device_id_str}: {e}", exc_info=True)
            return jsonify({"error": f"Failed to register new device: {str(e)}"}), 500

@bp.route("/<string:device_id_param>", methods=["GET"])
@login_required
def get_device_details(device_id_param):
    # ... (existing code) ...
    device = Device.query.filter_by(device_id=device_id_param).first()
    if not device: return jsonify({"error": "Device not found"}), 404
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to this device is forbidden"}), 403
    return jsonify(device.to_dict()), 200

@bp.route("/<string:device_id_param>", methods=["PUT"])
@login_required
def update_device_details(device_id_param):
    # ... (existing code, to be updated with DeviceUpdateSchema) ...
    device = Device.query.filter_by(device_id=device_id_param).first()
    if not device: return jsonify({"error": "Device not found"}), 404
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to update this device is forbidden"}), 403

    json_data = request.get_json()
    if not json_data: return jsonify({"error": "Request body must be JSON"}), 400

    try:
        # Using dump_only=() or partial=True might be needed if not all fields are expected
        # For PUT, usually all fields for update are optional in the payload.
        # A schema with all fields optional, or `partial=True` on load.
        # Let's assume DeviceUpdateSchema has fields as optional.
        loaded_data = device_update_schema.load(json_data)
    except Exception as err: # Marshmallow ValidationError
        logger.warning(f"Device update validation failed for {device_id_param}: {err.messages if hasattr(err, 'messages') else str(err)}")
        return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err, 'messages') else str(err)}), 400

    # Update only fields that are present in loaded_data (Marshmallow skips missing fields by default)
    if "device_name" in loaded_data: device.device_name = loaded_data["device_name"]
    if "os_version" in loaded_data: device.os_version = loaded_data["os_version"]
    if "status" in loaded_data: device.status = loaded_data["status"]
    if "platform" in loaded_data: device.platform = loaded_data["platform"] # If platform update is allowed
    device.last_seen = datetime.now(timezone.utc)

    try:
        db.session.commit()
        logger.info(f"Device details updated for {device_id_param} by user {current_user.username}")
        return jsonify(device.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating device details for {device_id_param}: {e}", exc_info=True)
        return jsonify({"error": f"Failed to update device: {str(e)}"}), 500


@bp.route("/<string:device_id_param>", methods=["DELETE"])
@login_required
def deregister_device(device_id_param):
    # ... (existing code) ...
    device = Device.query.filter_by(device_id=device_id_param).first()
    if not device: return jsonify({"error": "Device not found"}), 404
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to delete this device is forbidden"}), 403
    try:
        db.session.delete(device); db.session.commit()
        logger.info(f"Device {device_id_param} deregistered by user {current_user.username}.")
        return jsonify({"message": "Device deregistered successfully"}), 200
    except Exception as e:
        db.session.rollback(); logger.error(f"Error deregistering device {device_id_param}: {e}", exc_info=True)
        return jsonify({"error": f"Failed to deregister device: {str(e)}"}), 500

@bp.route("/heartbeat", methods=["POST"])
def device_heartbeat():
    # ... (existing code with API key validation) ...
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        logger.warning("Device heartbeat attempt missing X-API-Key header.")
        return jsonify({"error": "API key required (X-API-Key header)"}), 401
    data = request.get_json()
    if not data: return jsonify({"error": "Request body must be JSON"}), 400
    device_id_str = data.get("device_id")
    if not device_id_str: return jsonify({"error": "Missing device_id in payload"}), 400
    device = Device.query.filter_by(device_id=device_id_str).first()
    if not device:
        logger.warning(f"Heartbeat received for unknown device_id {device_id_str}.")
        return jsonify({"error": "Device not registered."}), 404
    if not device.api_key or device.api_key != api_key:
        logger.warning(f"Invalid API key for device_id {device_id_str} during heartbeat. Received: {api_key[:5]}...")
        return jsonify({"error": "Invalid API key."}), 403
    device.status = data.get("status", device.status)
    device.last_seen = datetime.now(timezone.utc)
    if "os_version" in data: device.os_version = data.get("os_version")
    if "device_name" in data: device.device_name = data.get("device_name")
    if "platform" in data: device.platform = data.get("platform")
    try:
        db.session.commit()
        return jsonify(device.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing heartbeat for device {device_id_str}: {e}", exc_info=True)
        return jsonify({"error": f"Failed to process heartbeat: {str(e)}"}), 500
