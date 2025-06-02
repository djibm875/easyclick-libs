#!/bin/python
from flask import request, jsonify
from . import bp
from app.models import Device, TaskAssignment, TaskDefinition # Added TaskAssignment, TaskDefinition
from app import db
from datetime import datetime, timezone
from flask_login import login_required, current_user
import logging
from .schemas import DeviceRegistrationSchema, DeviceUpdateSchema, DeviceTaskStatusUpdateSchema # Added DeviceTaskStatusUpdateSchema

logger = logging.getLogger(__name__)

device_registration_schema = DeviceRegistrationSchema()
device_update_schema = DeviceUpdateSchema()
device_task_status_update_schema = DeviceTaskStatusUpdateSchema() # New schema instance

# --- Existing User-Authenticated Device Routes (list, register, get_details, update_details, delete) ---
# ... (These are assumed to be present and correct from previous steps) ...
@bp.route("/", methods=["GET"])
@login_required
def list_devices():
    try:
        page = request.args.get("page", 1, type=int); per_page = request.args.get("per_page", 10, type=int)
        query = Device.query
        if current_user.role != "super_admin": query = query.filter(Device.tenant_id == current_user.tenant_id)
        status_filter = request.args.get("status"); platform_filter = request.args.get("platform")
        if status_filter: query = query.filter(Device.status == status_filter)
        if platform_filter: query = query.filter(Device.platform == platform_filter)
        devices_pagination = query.order_by(Device.registered_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        devices = devices_pagination.items
        return jsonify({"devices": [device.to_dict() for device in devices],"total": devices_pagination.total, "pages": devices_pagination.pages, "current_page": devices_pagination.page}), 200
    except Exception as e: logger.error(f"Error listing devices: {e}", exc_info=True); return jsonify({"error": str(e)}), 500

@bp.route("/register", methods=["POST"])
@login_required
def register_device():
    json_data = request.get_json();
    if not json_data: return jsonify({"error": "Request body must be JSON"}), 400
    try: loaded_data = device_registration_schema.load(json_data)
    except Exception as err: return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err,"messages") else str(err)}),400
    device_id_str = loaded_data["device_id"]; platform = loaded_data["platform"]
    device_name = loaded_data.get("device_name"); os_version = loaded_data.get("os_version")
    existing_device_globally = Device.query.filter_by(device_id=device_id_str).first()
    if existing_device_globally and existing_device_globally.tenant_id != current_user.tenant_id:
        return jsonify({"error": f"Device {device_id_str} already registered to a different tenant."}), 409
    target_tenant_id = current_user.tenant_id
    if not target_tenant_id: return jsonify({"error": "User not associated with a tenant."}), 400
    device_to_update_or_create = existing_device_globally
    if device_to_update_or_create:
        device_to_update_or_create.device_name=device_name if device_name is not None else device_to_update_or_create.device_name
        device_to_update_or_create.platform=platform; device_to_update_or_create.os_version=os_version if os_version is not None else device_to_update_or_create.os_version
        device_to_update_or_create.status="online"; device_to_update_or_create.last_seen=datetime.now(timezone.utc)
        try: db.session.commit(); return jsonify(device_to_update_or_create.to_dict()), 200
        except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500
    else:
        new_device = Device(device_id=device_id_str, device_name=device_name, platform=platform, os_version=os_version, status="online",
                            last_seen=datetime.now(timezone.utc), registered_at=datetime.now(timezone.utc), tenant_id=target_tenant_id)
        new_device.generate_api_key()
        try: db.session.add(new_device); db.session.commit(); return jsonify(new_device.to_dict_with_key()), 201
        except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500

@bp.route("/<string:device_id_param>", methods=["GET"])
@login_required
def get_device_details(device_id_param):
    device = Device.query.filter_by(device_id=device_id_param).first_or_404()
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id: return jsonify({"error": "Forbidden"}), 403
    return jsonify(device.to_dict()), 200

@bp.route("/<string:device_id_param>", methods=["PUT"])
@login_required
def update_device_details(device_id_param):
    device = Device.query.filter_by(device_id=device_id_param).first_or_404()
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id: return jsonify({"error": "Forbidden"}), 403
    json_data = request.get_json();
    if not json_data: return jsonify({"error": "Request body must be JSON"}), 400
    try: loaded_data = device_update_schema.load(json_data)
    except Exception as err: return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err,"messages") else str(err)}),400
    if "device_name" in loaded_data: device.device_name = loaded_data["device_name"]
    if "os_version" in loaded_data: device.os_version = loaded_data["os_version"]
    if "status" in loaded_data: device.status = loaded_data["status"]
    if "platform" in loaded_data: device.platform = loaded_data["platform"]
    device.last_seen = datetime.now(timezone.utc)
    try: db.session.commit(); return jsonify(device.to_dict()), 200
    except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500

@bp.route("/<string:device_id_param>", methods=["DELETE"])
@login_required
def deregister_device(device_id_param):
    device = Device.query.filter_by(device_id=device_id_param).first_or_404()
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id: return jsonify({"error": "Forbidden"}), 403
    try: db.session.delete(device); db.session.commit(); return jsonify({"message": "Device deregistered"}), 200
    except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500

@bp.route("/heartbeat", methods=["POST"]) # Device authenticated
def device_heartbeat():
    api_key = request.headers.get("X-API-Key")
    if not api_key: return jsonify({"error": "API key required"}), 401
    data = request.get_json();
    if not data: return jsonify({"error": "Request body must be JSON"}), 400
    device_id_str = data.get("device_id")
    if not device_id_str: return jsonify({"error": "Missing device_id in payload"}), 400
    device = Device.query.filter_by(device_id=device_id_str).first()
    if not device: return jsonify({"error": "Device not registered."}), 404
    if not device.api_key or device.api_key != api_key: return jsonify({"error": "Invalid API key."}), 403
    device.status = data.get("status", device.status); device.last_seen = datetime.now(timezone.utc)
    if "os_version" in data: device.os_version = data.get("os_version")
    if "device_name" in data: device.device_name = data.get("device_name")
    if "platform" in data: device.platform = data.get("platform")
    try: db.session.commit(); return jsonify(device.to_dict()), 200
    except Exception as e: db.session.rollback(); return jsonify({"error": str(e)}), 500

# --- New Device-Authenticated Task Endpoints ---

@bp.route("/agent/tasks", methods=["GET"]) # Renamed for clarity, could be /my_tasks
def device_get_assigned_tasks():
    """
    Allows a device (authenticated by API key) to fetch its pending tasks.
    """
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        logger.warning("Device get tasks attempt missing X-API-Key header.")
        return jsonify({"error": "API key required (X-API-Key header)"}), 401

    # Find device by API key. This ensures the device is who it claims to be.
    device = Device.query.filter_by(api_key=api_key).first()
    if not device:
        logger.warning(f"Invalid API key used for fetching tasks. Key prefix: {api_key[:5]}...")
        return jsonify({"error": "Invalid API key or device not found for this key."}), 403 # Or 404

    # Fetch pending tasks for this device
    # Could also include "running" if tasks can be retried or resumed.
    # For simplicity, only "pending" for now.
    tasks = TaskAssignment.query.filter_by(device_id=device.id, status="pending")\
                               .order_by(TaskAssignment.scheduled_at.asc()).all()

    # We need to return enough info for the device to execute the task, including script_body
    # Modifying TaskAssignment.to_dict() or creating a specific one might be needed.
    # For now, let's construct a custom response.
    tasks_response = []
    for task_assignment in tasks:
        tasks_response.append({
            "assignment_id": task_assignment.id,
            "task_definition_id": task_assignment.task_definition_id,
            "task_name": task_assignment.task_definition.name,
            "script_body": task_assignment.task_definition.script_body, # CRITICAL for execution
            "scheduled_at": task_assignment.scheduled_at.isoformat() if task_assignment.scheduled_at else None,
            "status": task_assignment.status # Should be "pending"
        })

    logger.info(f"Device {device.device_id} (ID: {device.id}) fetched {len(tasks_response)} pending tasks.")
    return jsonify(tasks_response), 200


@bp.route("/agent/tasks/<int:assignment_id>/status", methods=["POST"]) # Changed to POST for body
def device_update_task_status(assignment_id):
    """
    Allows a device (authenticated by API key) to update the status of one of its tasks.
    """
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        logger.warning(f"Device update task status attempt missing X-API-Key for assignment {assignment_id}.")
        return jsonify({"error": "API key required (X-API-Key header)"}), 401

    device = Device.query.filter_by(api_key=api_key).first()
    if not device:
        logger.warning(f"Invalid API key used for updating task {assignment_id}. Key prefix: {api_key[:5]}...")
        return jsonify({"error": "Invalid API key or device not found for this key."}), 403

    assignment = TaskAssignment.query.get(assignment_id)
    if not assignment:
        logger.warning(f"Device {device.device_id} tried to update non-existent task assignment {assignment_id}.")
        return jsonify({"error": "Task assignment not found."}), 404

    # Crucial check: Does this task assignment belong to *this* device?
    if assignment.device_id != device.id:
        logger.error(f"SECURITY: Device {device.device_id} (API Key OK) tried to update task assignment {assignment_id} which belongs to device {assignment.device_id}!")
        return jsonify({"error": "Forbidden: Task assignment does not belong to this device."}), 403

    json_data = request.get_json()
    if not json_data:
        return jsonify({"error": "Request body must be JSON"}), 400

    try:
        loaded_data = device_task_status_update_schema.load(json_data)
    except Exception as err: # Marshmallow ValidationError
        logger.warning(f"Device task {assignment_id} status update validation failed: {err.messages if hasattr(err, 'messages') else str(err)}")
        return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err, 'messages') else str(err)}), 400

    new_status = loaded_data["status"]
    # Potentially validate status transitions here (e.g., cannot go from 'completed' to 'running')
    # For now, device report is trusted if API key is valid and task belongs to device.

    assignment.status = new_status
    if new_status == "running" and not assignment.started_at:
        assignment.started_at = datetime.now(timezone.utc)
    elif new_status in ["completed", "failed", "cancelled"] and not assignment.completed_at:
        assignment.completed_at = datetime.now(timezone.utc)

    if "result_output" in loaded_data: # result_output is optional in schema
        assignment.result_output = loaded_data["result_output"]

    assignment.updated_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
        logger.info(f"Device {device.device_id} updated status of task assignment {assignment_id} to {new_status}.")
        return jsonify(assignment.to_dict()), 200 # Return updated assignment
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing status update for task assignment {assignment_id} by device {device.device_id}: {e}", exc_info=True)
        return jsonify({"error": "Could not update task assignment status", "message": str(e)}), 500
