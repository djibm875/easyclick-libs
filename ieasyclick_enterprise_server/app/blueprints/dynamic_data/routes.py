#!/bin/python
from flask import request, jsonify
from . import bp
from app import db
from app.models import Device, TaskAssignment, DynamicDataEntry # User for current_user (not used in submit directly)
from datetime import datetime, timezone
from flask_login import login_required, current_user # login_required for GET routes
from dateutil import parser as dateutil_parser
import logging

logger = logging.getLogger(__name__)

@bp.route("/submit", methods=["POST"])
def submit_dynamic_data():
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        logger.warning("Dynamic data submission missing X-API-Key header.")
        return jsonify({"error": "API key required (X-API-Key header)"}), 401

    data = request.get_json()
    if not data: return jsonify({"error": "Request body must be JSON"}), 400

    device_external_id = data.get("device_id")
    payload = data.get("payload")

    if not device_external_id or payload is None:
        return jsonify({"error": "Missing device_id or payload"}), 400

    device = Device.query.filter_by(device_id=device_external_id).first()
    if not device:
        logger.warning(f"Dynamic data received for unknown device_id {device_external_id}.")
        return jsonify({"error": "Device not found"}), 404

    if not device.api_key or device.api_key != api_key:
        logger.warning(f"Invalid API key for device_id {device_external_id} during data submission. Received: {api_key[:5]}...")
        return jsonify({"error": "Invalid API key."}), 403

    # API Key is valid, proceed
    tenant_id = device.tenant_id
    task_assignment_id = data.get("task_assignment_id")
    if task_assignment_id:
        task_assignment = TaskAssignment.query.get(task_assignment_id)
        if not task_assignment or task_assignment.device_id != device.id:
            return jsonify({"error": "Invalid task_assignment_id for this device"}), 400
        if task_assignment.task_definition.tenant_id != tenant_id:
             return jsonify({"error": "Task assignment tenant mismatch"}), 400

    reported_at_str = data.get("reported_at")
    reported_at_dt = datetime.now(timezone.utc)
    if reported_at_str:
        try:
            reported_at_dt = dateutil_parser.isoparse(reported_at_str)
            if reported_at_dt.tzinfo is None: reported_at_dt = reported_at_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({"error": "Invalid reported_at timestamp format. Use ISO 8601."}), 400

    try:
        entry = DynamicDataEntry(
            device_id=device.id, tenant_id=tenant_id, task_assignment_id=task_assignment_id,
            data_type=data.get("data_type"), data_payload=payload, reported_at=reported_at_dt
        )
        db.session.add(entry); db.session.commit()
        # logger.info(f"Dynamic data submitted for device {device_external_id}, type {data.get('data_type')}")
        return jsonify(entry.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error storing dynamic data for device {device_external_id}: {e}", exc_info=True)
        return jsonify({"error": "Could not store dynamic data", "message": str(e)}), 500

@bp.route("/", methods=["GET"])
@login_required
def list_dynamic_data():
    try:
        query = DynamicDataEntry.query
        if current_user.role != "super_admin":
            if not current_user.tenant_id: return jsonify({"error": "User not associated with a tenant"}), 400
            query = query.filter(DynamicDataEntry.tenant_id == current_user.tenant_id)
        else:
            filter_tenant_id = request.args.get("tenant_id", type=int)
            if filter_tenant_id: query = query.filter(DynamicDataEntry.tenant_id == filter_tenant_id)
        device_ext_id = request.args.get("device_id"); data_type = request.args.get("data_type")
        task_id = request.args.get("task_assignment_id", type=int)
        start_date_str = request.args.get("start_date"); end_date_str = request.args.get("end_date")
        if device_ext_id:
            device = Device.query.filter_by(device_id=device_ext_id).first()
            if device:
                if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
                    return jsonify({"error": "Access to this device data is forbidden"}), 403
                query = query.filter(DynamicDataEntry.device_id == device.id)
            else: return jsonify([]), 200
        if data_type: query = query.filter(DynamicDataEntry.data_type == data_type)
        if task_id: query = query.filter(DynamicDataEntry.task_assignment_id == task_id)
        if start_date_str:
            try: query = query.filter(DynamicDataEntry.reported_at >= dateutil_parser.isoparse(start_date_str).replace(tzinfo=timezone.utc))
            except ValueError: return jsonify({"error": "Invalid start_date format"}), 400
        if end_date_str:
            try: query = query.filter(DynamicDataEntry.reported_at <= dateutil_parser.isoparse(end_date_str).replace(tzinfo=timezone.utc))
            except ValueError: return jsonify({"error": "Invalid end_date format"}), 400
        page = request.args.get("page", 1, type=int); per_page = request.args.get("per_page", 20, type=int)
        data_pagination = query.order_by(DynamicDataEntry.reported_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        entries = data_pagination.items
        return jsonify({"data_entries": [entry.to_dict() for entry in entries], "total": data_pagination.total, "pages": data_pagination.pages, "current_page": data_pagination.page}), 200
    except Exception as e:
        logger.error(f"Error listing dynamic data: {e}", exc_info=True)
        return jsonify({"error": "Could not retrieve dynamic data", "message": str(e)}), 500

@bp.route("/device/<string:device_external_id>", methods=["GET"])
@login_required
def get_data_for_device(device_external_id):
    device = Device.query.filter_by(device_id=device_external_id).first_or_404()
    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to this device data is forbidden"}), 403
    query = DynamicDataEntry.query.filter_by(device_id=device.id)
    page = request.args.get("page", 1, type=int); per_page = request.args.get("per_page", 20, type=int)
    data_pagination = query.order_by(DynamicDataEntry.reported_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"data_entries": [entry.to_dict() for entry in data_pagination.items], "total": data_pagination.total, "pages": data_pagination.pages, "current_page": data_pagination.page}), 200

@bp.route("/task/<int:task_assignment_id>", methods=["GET"])
@login_required
def get_data_for_task(task_assignment_id):
    assignment = TaskAssignment.query.get_or_404(task_assignment_id)
    if current_user.role != "super_admin" and assignment.task_definition.tenant_id != current_user.tenant_id:
        return jsonify({"error": "Access to this task data is forbidden"}), 403
    query = DynamicDataEntry.query.filter_by(task_assignment_id=task_assignment_id)
    page = request.args.get("page", 1, type=int); per_page = request.args.get("per_page", 20, type=int)
    data_pagination = query.order_by(DynamicDataEntry.reported_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"data_entries": [entry.to_dict() for entry in data_pagination.items], "total": data_pagination.total, "pages": data_pagination.pages, "current_page": data_pagination.page}), 200
