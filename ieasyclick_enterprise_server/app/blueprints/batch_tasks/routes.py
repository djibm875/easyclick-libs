#!/bin/python
from flask import request, jsonify
from . import bp
from app import db
from app.models import Device, TaskDefinition, TaskAssignment, User
from datetime import datetime, timezone
from flask_login import login_required, current_user
import logging
from .schemas import TaskDefinitionSchema, TaskAssignmentSchema, TaskAssignmentStatusUpdateSchema # Schemas
from dateutil import parser as dateutil_parser # For parsing scheduled_at string to datetime

logger = logging.getLogger(__name__)

task_definition_schema = TaskDefinitionSchema()
task_assignment_schema = TaskAssignmentSchema()
task_assignment_status_update_schema = TaskAssignmentStatusUpdateSchema()

# --- TaskDefinition Endpoints (from previous step, assumed correct) ---
@bp.route("/definitions", methods=["POST"])
@login_required
def create_task_definition():
    json_data = request.get_json();
    if not json_data: return jsonify({"error": "Request body must be JSON"}), 400
    try: loaded_data = task_definition_schema.load(json_data)
    except Exception as err: return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err, "messages") else str(err)}), 400
    name = loaded_data["name"]; script_body = loaded_data["script_body"]; description = loaded_data.get("description")
    target_tenant_id = None
    if current_user.role == "super_admin":
        target_tenant_id = loaded_data.get("tenant_id_for_super_admin")
        if not target_tenant_id: return jsonify({"error": "Super admin must specify tenant_id_for_super_admin"}), 400
    else:
        if not current_user.tenant_id: return jsonify({"error": "User not associated with a tenant"}), 400
        target_tenant_id = current_user.tenant_id
    if TaskDefinition.query.filter_by(name=name, tenant_id=target_tenant_id).first():
        return jsonify({"error": f"Task definition name {name} already exists in this tenant"}), 409
    try:
        definition = TaskDefinition(name=name, description=description, script_body=script_body, tenant_id=target_tenant_id)
        db.session.add(definition); db.session.commit()
        logger.info(f"TaskDefinition {name} created for tenant {target_tenant_id} by user {current_user.username}.")
        return jsonify(definition.to_dict()), 201
    except Exception as e:
        db.session.rollback(); logger.error(f"Error creating task definition {name}: {e}", exc_info=True)
        return jsonify({"error": "Could not create task definition", "message": str(e)}), 500

@bp.route("/definitions", methods=["GET"])
@login_required
def list_task_definitions():
    try:
        query = TaskDefinition.query
        if current_user.role != "super_admin":
            if not current_user.tenant_id: return jsonify({"error": "User not associated with a tenant"}), 400
            query = query.filter(TaskDefinition.tenant_id == current_user.tenant_id)
        else:
            filter_tenant_id = request.args.get("tenant_id", type=int)
            if filter_tenant_id: query = query.filter(TaskDefinition.tenant_id == filter_tenant_id)
        definitions = query.all()
        return jsonify([d.to_dict() for d in definitions]), 200
    except Exception as e: logger.error(f"Error listing task definitions: {e}", exc_info=True); return jsonify({"error": str(e)}), 500

@bp.route("/definitions/<int:def_id>", methods=["GET"])
@login_required
def get_task_definition(def_id):
    try:
        definition = TaskDefinition.query.get_or_404(def_id)
        if current_user.role != "super_admin" and definition.tenant_id != current_user.tenant_id:
            return jsonify({"error": "Access to this task definition is forbidden"}), 403
        return jsonify(definition.to_dict()), 200
    except Exception as e: logger.error(f"Error getting task def {def_id}: {e}", exc_info=True); return jsonify({"error": str(e)}), 404

@bp.route("/definitions/<int:def_id>", methods=["PUT"])
@login_required
def update_task_definition(def_id):
    definition = TaskDefinition.query.get_or_404(def_id)
    if current_user.role != "super_admin" and definition.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to update this task definition is forbidden"}), 403
    json_data = request.get_json();
    if not json_data: return jsonify({"error": "Request body must be JSON"}), 400
    try: loaded_data = task_definition_schema.load(json_data, partial=("name", "description", "script_body"))
    except Exception as err: return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err, "messages") else str(err)}), 400
    if "name" in loaded_data and loaded_data["name"] != definition.name:
        if TaskDefinition.query.filter(TaskDefinition.id != def_id, TaskDefinition.name == loaded_data["name"], TaskDefinition.tenant_id == definition.tenant_id).first():
            return jsonify({"error": f"Task definition name {loaded_data['name']} already exists in this tenant"}), 409
        definition.name = loaded_data["name"]
    if "description" in loaded_data: definition.description = loaded_data["description"]
    if "script_body" in loaded_data: definition.script_body = loaded_data["script_body"]
    definition.updated_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
        logger.info(f"TaskDefinition {def_id} ({definition.name}) updated by user {current_user.username}.")
        return jsonify(definition.to_dict()), 200
    except Exception as e: db.session.rollback(); logger.error(f"Error updating task def {def_id}: {e}", exc_info=True); return jsonify({"error": str(e)}), 500

@bp.route("/definitions/<int:def_id>", methods=["DELETE"])
@login_required
def delete_task_definition(def_id):
    definition = TaskDefinition.query.get_or_404(def_id)
    if current_user.role != "super_admin" and definition.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to delete this task definition is forbidden"}), 403
    try:
        db.session.delete(definition); db.session.commit()
        logger.info(f"TaskDefinition {def_id} ({definition.name}) deleted by user {current_user.username}.")
        return jsonify({"message": "Task definition deleted successfully"}), 200
    except Exception as e: db.session.rollback(); logger.error(f"Error deleting task def {def_id}: {e}", exc_info=True); return jsonify({"error": str(e)}), 500

# --- TaskAssignment Endpoints ---

@bp.route("/assign", methods=["POST"])
@login_required
def assign_task():
    json_data = request.get_json()
    if not json_data: return jsonify({"error": "Request body must be JSON"}), 400

    try:
        loaded_data = task_assignment_schema.load(json_data)
    except Exception as err: # Marshmallow ValidationError
        logger.warning(f"Task assignment validation failed: {err.messages if hasattr(err, 'messages') else str(err)}")
        return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err, 'messages') else str(err)}), 400

    task_def_id = loaded_data["task_definition_id"]
    device_external_ids = loaded_data["device_ids"] # Validated by schema: list of strings, not empty

    task_definition = TaskDefinition.query.get(task_def_id)
    if not task_definition:
        return jsonify({"error": "Task definition not found"}), 404

    if current_user.role != "super_admin" and task_definition.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to use this task definition is forbidden"}), 403

    target_tenant_id_for_devices = task_definition.tenant_id
    assignments_created = []
    errors = []

    scheduled_at_val = datetime.now(timezone.utc) # Default
    if loaded_data.get("scheduled_at"): # Optional field, validated as ISO string by schema
        try:
            scheduled_at_val = dateutil_parser.isoparse(loaded_data["scheduled_at"])
            if scheduled_at_val.tzinfo is None: # Ensure timezone aware
                scheduled_at_val = scheduled_at_val.replace(tzinfo=timezone.utc)
        except ValueError: # Should not happen if regex in schema is robust
            errors.append({"scheduled_at": "Invalid datetime format after regex validation."})
            # This indicates an issue with schema regex or this parsing logic

    if errors: # If scheduled_at parsing failed (unlikely if regex is good)
         return jsonify({"message": "Task assignment failed due to errors.", "errors": errors}), 400


    for dev_ext_id in device_external_ids:
        device = Device.query.filter_by(device_id=dev_ext_id).first()
        if not device:
            errors.append({"device_id": dev_ext_id, "error": "Device not found"})
            continue
        if device.tenant_id != target_tenant_id_for_devices:
            errors.append({"device_id": dev_ext_id, "error": f"Device does not belong to tenant {target_tenant_id_for_devices}"})
            continue

        try:
            assignment = TaskAssignment(
                task_definition_id=task_def_id,
                device_id=device.id, # Use Device PK
                status="pending",
                scheduled_at=scheduled_at_val
            )
            db.session.add(assignment)
            assignments_created.append(assignment)
        except Exception as e:
            db.session.rollback() # Rollback immediately on first error within loop for this device
            errors.append({"device_id": dev_ext_id, "error": f"Could not create assignment: {str(e)}"})
            # Decide if to continue with other devices or stop all on first error
            # Current: continues, collects all errors

    if assignments_created and not errors: # Only commit if no errors encountered during device processing
        try:
            db.session.commit()
            logger.info(f"{len(assignments_created)} task assignments created for task_def {task_def_id} by user {current_user.username}.")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error committing task assignments for task_def {task_def_id}: {e}", exc_info=True)
            # All assignments failed to commit, return a general error
            return jsonify({"error": "Failed to commit assignments", "message": str(e)}), 500
    elif errors: # If there were errors for some devices, don't commit any.
        db.session.rollback() # Ensure nothing is committed
        logger.warning(f"Task assignment for task_def {task_def_id} by {current_user.username} failed for some devices. No assignments created. Errors: {errors}")
        # Return specific errors for devices
        return jsonify({"message": "Task assignment failed for one or more devices. No assignments created.", "errors": errors}), 400


    response_status = 201
    if errors: # This part should not be reached if we fail all on first error above.
               # If we are returning partial success (some assigned, some not), then 207.
               # Current logic: if any error in device loop, all are rolled back.
        response_status = 400 # Or 207 if partial success was allowed

    return jsonify({
        "message": "Task assignment processing complete." if not errors else "Task assignment processing completed with errors.",
        "assignments_created": [a.to_dict() for a in assignments_created if a.id], # Only those with ID (committed)
        "errors": errors
    }), response_status


@bp.route("/assignments", methods=["GET"])
@login_required
def list_task_assignments():
    # ... (existing, no payload validation)
    try:
        query = TaskAssignment.query.join(TaskDefinition)
        if current_user.role != "super_admin":
            if not current_user.tenant_id: return jsonify({"error": "User not associated with a tenant"}), 400
            query = query.filter(TaskDefinition.tenant_id == current_user.tenant_id)
        else:
            filter_tenant_id = request.args.get("tenant_id", type=int)
            if filter_tenant_id: query = query.filter(TaskDefinition.tenant_id == filter_tenant_id)
        device_ext_id = request.args.get("device_id"); status = request.args.get("status")
        task_def_filter_id = request.args.get("task_definition_id", type=int)
        if device_ext_id:
            query = query.join(Device).filter(Device.device_id == device_ext_id)
        if status: query = query.filter(TaskAssignment.status == status)
        if task_def_filter_id: query = query.filter(TaskAssignment.task_definition_id == task_def_filter_id)
        assignments = query.order_by(TaskAssignment.created_at.desc()).all()
        return jsonify([a.to_dict() for a in assignments]), 200
    except Exception as e: logger.error(f"Error listing task assignments: {e}", exc_info=True); return jsonify({"error": str(e)}), 500

@bp.route("/assignments/<int:assignment_id>", methods=["GET"])
@login_required
def get_task_assignment(assignment_id):
    # ... (existing, no payload validation)
    assignment = TaskAssignment.query.get_or_404(assignment_id)
    if current_user.role != "super_admin" and assignment.task_definition.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to this task assignment is forbidden"}), 403
    return jsonify(assignment.to_dict()), 200

@bp.route("/assignments/<int:assignment_id>/status", methods=["PUT"])
@login_required
def update_task_assignment_status(assignment_id):
    assignment = TaskAssignment.query.get_or_404(assignment_id)
    if current_user.role != "super_admin" and assignment.task_definition.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to update this task assignment is forbidden"}), 403

    json_data = request.get_json()
    if not json_data: return jsonify({"error": "Request body must be JSON"}), 400

    try:
        loaded_data = task_assignment_status_update_schema.load(json_data)
    except Exception as err: # Marshmallow ValidationError
        logger.warning(f"TaskAssignment {assignment_id} status update validation failed: {err.messages if hasattr(err, 'messages') else str(err)}")
        return jsonify({"error": "Input validation failed", "messages": err.messages if hasattr(err, 'messages') else str(err)}), 400

    new_status = loaded_data["status"]
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
        logger.info(f"TaskAssignment {assignment_id} status updated to {new_status} by {current_user.username}.")
        return jsonify(assignment.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating status for TaskAssignment {assignment_id}: {e}", exc_info=True)
        return jsonify({"error": "Could not update task assignment status", "message": str(e)}), 500

@bp.route("/assignments/device/<string:device_external_id>", methods=["GET"])
@login_required
def get_tasks_for_device(device_external_id):
    # ... (existing, no payload validation)
    device = Device.query.filter_by(device_id=device_external_id).first_or_404()
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to this device tasks is forbidden"}), 403
    try:
        assignments = TaskAssignment.query.filter_by(device_id=device.id).order_by(TaskAssignment.scheduled_at.desc()).all()
        return jsonify([a.to_dict() for a in assignments]), 200
    except Exception as e: logger.error(f"Error getting tasks for device {device_external_id}: {e}", exc_info=True); return jsonify({"error": str(e)}), 500
