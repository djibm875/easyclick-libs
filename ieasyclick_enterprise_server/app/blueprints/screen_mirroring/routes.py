#!/bin/python
from flask import jsonify, request
from . import bp
from app.models import Device
from app import redis_client # Import redis_client
from datetime import datetime, timezone, timedelta # timedelta for TTL
from flask_login import login_required, current_user
import secrets # For token generation
import json # For storing dict as JSON in Redis
import logging

logger = logging.getLogger(__name__)

# Using the shared_session_store for active session *state* (like status)
# The new token is for *authorizing* the SocketIO connection itself.
from app.utils.session_store import shared_session_store as active_sessions_store

# Configuration for the SocketIO connection token
SOCKETIO_CONN_TOKEN_TTL_SECONDS = 60 # Token valid for 60 seconds to establish connection

@bp.route("/start/<string:device_id_param>", methods=["POST"])
@login_required
def start_mirroring_session(device_id_param):
    device = Device.query.filter_by(device_id=device_id_param).first()
    if not device:
        logger.warning(f"Start mirroring attempt for unknown device: {device_id_param} by user {current_user.username}")
        return jsonify({"error": "Device not found"}), 404

    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
        logger.warning(f"User {current_user.username} (tenant {current_user.tenant_id}) forbidden to start mirror for device {device_id_param} (tenant {device.tenant_id}).")
        return jsonify({"error": "Access to this device is forbidden"}), 403

    if device.status != "online":
        logger.info(f"Attempt to start mirror for device {device_id_param} which is not online (status: {device.status}).")
        return jsonify({"error": "Device is not online"}), 400

    # Check if a session *state* already exists (using the RedisSessionStore)
    existing_session_state = active_sessions_store.get_session(device_id_param)
    if existing_session_state:
        logger.info(f"Mirroring session for device {device_id_param} already active or pending.")
        # If already active, we might not need a new SocketIO token, or we could issue one if client needs to reconnect.
        # For now, let's assume if state exists, we return it. Client handles if it needs a new token.
        # Or, always generate a new token for a new attempt to connect via SocketIO.
        # Let's always generate a new token to simplify client logic for retries.
        pass # Continue to generate a new connection token

    # Generate a new short-lived token for SocketIO connection authorization
    sio_conn_token = secrets.token_urlsafe(32)
    token_redis_key = f"sio_mirror_token:{sio_conn_token}"
    token_data = {
        "device_id": device.device_id, # Store external device_id for verification
        "user_id": current_user.id,
        "tenant_id": device.tenant_id, # For potential cross-check
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        redis_client.setex(token_redis_key, SOCKETIO_CONN_TOKEN_TTL_SECONDS, json.dumps(token_data))
        logger.info(f"Generated SocketIO connection token for device {device_id_param}, user {current_user.username}. Token key: {token_redis_key[:45]}...")
    except Exception as e:
        logger.error(f"Failed to store SocketIO connection token in Redis for device {device_id_param}: {e}", exc_info=True)
        return jsonify({"error": "Failed to initiate mirroring session (token storage error)"}), 500


    # Session *state* management (using shared_session_store - RedisSessionStore)
    session_info_for_state = {
        "device_id": device_id_param,
        "tenant_id": device.tenant_id,
        "status": "pending_sio_connection", # New status: waiting for SocketIO client to connect with token
        "started_by_user_id": current_user.id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        # "sio_conn_token": sio_conn_token # DO NOT put the token itself in the long-lived session state if it's sensitive
                                        # The token is short-lived in Redis itself.
    }
    # Set with a reasonable expiry for the session state, e.g., 24 hours
    active_sessions_store.set_session(device_id_param, session_info_for_state, expiry_seconds=24 * 60 * 60)

    logger.info(f"Mirroring session initiated for device {device_id_param} by user {current_user.username}. SocketIO token generated.")
    # Return the main session info AND the short-lived SocketIO connection token
    return jsonify({
        "message": "Screen mirroring session initiated",
        "session": session_info_for_state, # The session state
        "sio_conn_token": sio_conn_token     # The token for client to use for SocketIO connection
    }), 202

@bp.route("/stop/<string:device_id_param>", methods=["POST"])
@login_required
def stop_mirroring_session(device_id_param):
    session_info = active_sessions_store.get_session(device_id_param)
    if not session_info:
        logger.info(f"Stop mirroring request for device {device_id_param}, but no active session found.")
        return jsonify({"error": "No active mirroring session found for this device"}), 404

    if current_user.role != "super_admin" and session_info.get("tenant_id") != current_user.tenant_id:
        # Or check session_info.get("started_by_user_id") == current_user.id
        logger.warning(f"User {current_user.username} forbidden to stop mirror session for device {device_id_param} (owned by tenant {session_info.get('tenant_id')}).")
        return jsonify({"error": "Access to stop this session is forbidden"}), 403

    deleted = active_sessions_store.delete_session(device_id_param)
    if deleted:
        logger.info(f"Screen mirroring session for device {device_id_param} stopped by user {current_user.username}.")
    else:
        logger.warning(f"Failed to delete screen mirroring session for device {device_id_param} from store (already gone?).")

    # Also attempt to delete any pending SIO connection tokens if they exist, though they have TTL
    # This requires iterating keys in Redis or having a known pattern.
    # For now, rely on TTL of sio_conn_token.

    return jsonify({"message": "Screen mirroring session stop request processed"}), 200

@bp.route("/status/<string:device_id_param>", methods=["GET"])
@login_required
def get_mirroring_session_status(device_id_param):
    device = Device.query.filter_by(device_id=device_id_param).first()
    if not device:
        logger.info(f"Mirroring status request for unknown device: {device_id_param}")
        return jsonify({"error": "Device not found"}), 404

    if current_user.role != "super_admin" and device.tenant_id != current_user.tenant_id:
        logger.warning(f"User {current_user.username} forbidden to get mirror status for device {device_id_param} (tenant {device.tenant_id}).")
        return jsonify({"error": "Access to this device status is forbidden"}), 403

    session_info = active_sessions_store.get_session(device_id_param)
    if session_info:
        if current_user.role != "super_admin" and session_info.get("tenant_id") != current_user.tenant_id:
            active_sessions_store.delete_session(device_id_param)
            logger.error(f"Session info tenant mismatch for device {device_id_param} during status check by {current_user.username}. Session cleared.")
            return jsonify({"error": "Session info mismatch, session cleared."}), 500
        return jsonify({"session": session_info}), 200
    else:
        logger.info(f"No active mirroring session found for device {device_id_param} during status check.")
        return jsonify({"message": "No active mirroring session for this device"}), 404
