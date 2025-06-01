#!/bin/python
from app import socketio, redis_client # Import redis_client
from flask_socketio import emit, join_room, leave_room, disconnect, session as socketio_session # Added disconnect, socketio_session
from flask import request, current_app # current_app for accessing app context if needed
from app.utils.session_store import shared_session_store as active_sessions_store
import logging
import json # For loading token data from Redis

logger = logging.getLogger(__name__)

@socketio.on("connect", namespace="/mirroring")
def handle_mirroring_connect():
    """
    Handles new SocketIO connections to the /mirroring namespace.
    Authenticates the connection using a short-lived token passed as a query parameter.
    """
    auth_token = request.args.get("token")
    sid = request.sid
    logger.info(f"Connection attempt to /mirroring namespace from SID {sid} with token: {auth_token[:10] if auth_token else 'No token'}.")

    if not auth_token:
        logger.warning(f"SID {sid} connection rejected: No token provided.")
        # disconnect(sid, silent=True) # Can disconnect explicitly
        return False # Reject connection

    token_redis_key = f"sio_mirror_token:{auth_token}"
    try:
        token_data_json = redis_client.get(token_redis_key)
        if not token_data_json:
            logger.warning(f"SID {sid} connection rejected: Token not found in Redis or expired. Key: {token_redis_key[:55]}...")
            return False # Reject connection

        token_data = json.loads(token_data_json)
        device_id = token_data.get("device_id")
        user_id = token_data.get("user_id")
        # tenant_id = token_data.get("tenant_id") # Can be used for further validation if needed

        if not device_id or not user_id:
            logger.error(f"SID {sid} connection rejected: Invalid token data (missing device_id or user_id). Token key: {token_redis_key[:55]}...")
            # Consider deleting the malformed token from Redis if it was not structured as expected
            redis_client.delete(token_redis_key) # Clean up malformed token
            return False

        # Token is valid and data retrieved. Store essential info in SocketIO session.
        socketio_session["device_id"] = device_id
        socketio_session["user_id"] = user_id
        # socketio_session["tenant_id"] = tenant_id
        logger.info(f"SID {sid} successfully authenticated for device_id: {device_id}, user_id: {user_id}.")

        # Consume the token by deleting it from Redis (single-use for connection)
        redis_client.delete(token_redis_key)
        logger.debug(f"Consumed (deleted) SocketIO connection token: {token_redis_key[:55]}...")

        emit("connection_ack", {"sid": sid, "message": "Authenticated and connected."})
        return True # Accept connection

    except redis.exceptions.RedisError as e:
        logger.error(f"SID {sid} connection attempt failed due to Redis error: {e}", exc_info=True)
        return False # Reject on Redis error
    except json.JSONDecodeError as e:
        logger.error(f"SID {sid} connection rejected: Failed to decode token data from Redis. Key: {token_redis_key[:55]}... Error: {e}", exc_info=True)
        redis_client.delete(token_redis_key) # Clean up bad token
        return False
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"SID {sid} connection attempt failed due to unexpected error: {e}", exc_info=True)
        return False


@socketio.on("join_mirror_session", namespace="/mirroring")
def handle_join_mirror_session(data):
    # device_id from client payload (data.get("device_id"))
    # device_id_from_sio_session from socketio_session["device_id"] (validated on connect)

    sid = request.sid
    # Retrieve validated device_id from the SocketIO session
    device_id_from_sio_session = socketio_session.get("device_id")
    user_id_from_sio_session = socketio_session.get("user_id")

    if not device_id_from_sio_session or not user_id_from_sio_session:
        logger.warning(f"SID {sid} attempted to join session without prior authentication in SocketIO session.")
        emit("error", {"message": "Not authenticated for session operations."})
        disconnect(sid) # Force disconnect
        return

    client_sent_device_id = data.get("device_id")
    logger.debug(f"SID {sid} attempting to join mirror session. Validated device_id: {device_id_from_sio_session}, Client sent: {client_sent_device_id}, User: {user_id_from_sio_session}")

    if not client_sent_device_id:
        logger.warning(f"join_mirror_session failed for SID {sid}: device_id missing in payload.")
        emit("error", {"message": "device_id missing in join_mirror_session payload."})
        return

    if client_sent_device_id != device_id_from_sio_session:
        logger.error(f"SID {sid} tried to join room for device_id {client_sent_device_id} but was authenticated for {device_id_from_sio_session}. Disconnecting.")
        emit("error", {"message": "Device ID mismatch. Authorization error."})
        disconnect(sid)
        return

    # Check if the session *state* is still considered active by the server (using shared_session_store)
    session_state = active_sessions_store.get_session(device_id_from_sio_session)
    if not session_state: # or session_state.get("status") not in ["pending_sio_connection", "active_streaming_etc"]
        logger.warning(f"SID {sid} tried to join session for device_id {device_id_from_sio_session}, but no active HTTP session state found or state is not valid for joining.")
        emit("error", {"message": "Mirroring session not active or not found. Please (re)start via API."})
        # Optionally disconnect, or just prevent joining room
        return

    # Update session state if needed (e.g., from "pending_sio_connection" to "client_joined_viewer")
    # session_state["status"] = "client_joined_viewer"
    # session_state["viewers"] = session_state.get("viewers", 0) + 1
    # active_sessions_store.set_session(device_id_from_sio_session, session_state, expiry_seconds=24*60*60)


    room_id = f"mirror_{device_id_from_sio_session}"
    join_room(room_id) # SID joins the room for this device_id
    logger.info(f"Client SID {sid} (User: {user_id_from_sio_session}) successfully joined room {room_id} for device_id {device_id_from_sio_session}")
    emit("joined_session", {"room": room_id, "message": f"Successfully joined mirroring session for {device_id_from_sio_session}"})


@socketio.on("leave_mirror_session", namespace="/mirroring")
def handle_leave_mirror_session(data):
    sid = request.sid
    device_id_from_sio_session = socketio_session.get("device_id")
    user_id_from_sio_session = socketio_session.get("user_id") # For logging

    if not device_id_from_sio_session: # Should not happen if connect was successful
        logger.warning(f"SID {sid} attempted to leave session without device_id in SocketIO session.")
        return

    client_sent_device_id = data.get("device_id")
    if not client_sent_device_id or client_sent_device_id != device_id_from_sio_session:
        logger.warning(f"SID {sid} sent leave request with mismatched device_id. Expected {device_id_from_sio_session}, got {client_sent_device_id}.")
        # Potentially ignore or just use device_id_from_sio_session

    room_id = f"mirror_{device_id_from_sio_session}"
    leave_room(room_id)
    logger.info(f"Client SID {sid} (User: {user_id_from_sio_session}) left room {room_id} for device_id {device_id_from_sio_session}")
    emit("left_session", {"room": room_id, "message": f"Successfully left mirroring session for {device_id_from_sio_session}"})

    # Update session state viewers count if implementing that
    # session_state = active_sessions_store.get_session(device_id_from_sio_session)
    # if session_state:
    #     session_state["viewers"] = max(0, session_state.get("viewers", 1) - 1)
    #     if session_state["viewers"] == 0 and session_state.get("status") == "client_joined_viewer":
    #          # Optionally change status if no viewers left, or rely on TTL for session state
    #          # session_state["status"] = "device_streaming_no_viewers"
    #          pass
    #     active_sessions_store.set_session(device_id_from_sio_session, session_state, expiry_seconds=24*60*60)
    #     logger.info(f"Updated viewer count for device {device_id} due to disconnect of SID {sid}.")


@socketio.on("screen_data_from_device", namespace="/mirroring")
def handle_screen_data_from_device(data): # This comes from the device agent, not browser client
    # This handler needs its own authentication mechanism if devices connect via SocketIO.
    # For now, assuming it is a trusted source or uses a different auth method.
    # If devices also use tokens, theyd connect to a different namespace or pass a device_api_key.

    device_id = data.get("device_id") # Device agent identifies itself
    frame_data = data.get("frame")
    if not device_id or not frame_data:
        logger.debug("screen_data_from_device: Received event with missing device_id or frame_data.")
        return

    logger.debug(f"Screen data received from device agent for {device_id}.")
    # Check if there is an active mirroring session state for this device
    session_state = active_sessions_store.get_session(device_id)
    if not session_state: # or session_state.get("status") not in ["client_joined_viewer", "pending_sio_connection"] etc.
        logger.warning(f"Device agent for {device_id} sent screen data, but no active/valid mirroring session state found. Ignoring.")
        return

    # Update session status if this is the first frame from device
    # if session_state.get("status") == "pending_sio_connection": # Or a state indicating device should connect
    #    session_state["status"] = "streaming_from_device"
    #    active_sessions_store.set_session(device_id, session_state, expiry_seconds=24*60*60)


    room_id = f"mirror_{device_id}"
    # Relay this frame to all browser clients (viewers) in the room for this device
    socketio.emit("screen_update", {"device_id": device_id, "frame": "placeholder_if_too_large_for_log"}, room=room_id, namespace="/mirroring")


@socketio.on("control_event_from_client", namespace="/mirroring")
def handle_control_event_from_client(data):
    sid = request.sid
    device_id_from_sio_session = socketio_session.get("device_id")
    user_id_from_sio_session = socketio_session.get("user_id")

    if not device_id_from_sio_session or not user_id_from_sio_session:
        logger.warning(f"SID {sid} sent control event without prior authentication in SocketIO session.")
        emit("error", {"message": "Not authenticated for control operations."})
        disconnect(sid)
        return

    client_sent_device_id = data.get("device_id")
    event_data = data.get("event")

    if not client_sent_device_id or client_sent_device_id != device_id_from_sio_session:
        logger.warning(f"SID {sid} sent control event with mismatched device_id. Expected {device_id_from_sio_session}, got {client_sent_device_id}.")
        emit("error", {"message": "Device ID mismatch for control event."})
        return

    if not event_data:
        logger.warning(f"SID {sid} control_event for device {device_id_from_sio_session} missing event_data.")
        emit("error", {"message": "control_event missing event data"})
        return

    # Check server-side session state to ensure session is still valid / active
    session_state = active_sessions_store.get_session(device_id_from_sio_session)
    if not session_state: # or check specific status if needed
        logger.warning(f"SID {sid} (User {user_id_from_sio_session}) sent control event for device {device_id_from_sio_session}, but no active session state found.")
        emit("error", {"message": "No active session or permission denied to control this device."})
        return

    logger.info(f"Control event from client SID {sid} (User {user_id_from_sio_session}) for device {device_id_from_sio_session}: {event_data}")
    # Placeholder: Relay this event to the specific device agent
    # This would require the device agent to be connected, perhaps on another SocketIO namespace or room,
    # or via another communication channel (e.g., a message queue).
    # For example: socketio.emit("device_command", {"event": event_data}, room=f"device_agent_{device_id_from_sio_session}")
    emit("control_ack", {"message": "Control event received, placeholder for device relay.", "event_sent": event_data})


@socketio.on("disconnect", namespace="/mirroring")
def handle_mirroring_disconnect():
    sid = request.sid
    device_id = socketio_session.get("device_id") # Get device_id if stored during connect
    user_id = socketio_session.get("user_id") # Get user_id if stored

    logger.info(f"Client disconnected from /mirroring namespace: SID {sid}, DeviceID (from session): {device_id}, UserID (from session): {user_id}")

    if device_id:
        # If tracking viewers per device session state, decrement here
        # session_state = active_sessions_store.get_session(device_id)
        # if session_state:
        #     session_state["viewers"] = max(0, session_state.get("viewers", 1) - 1)
        #     if session_state["viewers"] == 0 and session_state.get("status") == "client_joined_viewer":
        #          # Optionally change status if no viewers left, or rely on TTL for session state
        #          # session_state["status"] = "device_streaming_no_viewers"
        #          pass
        #     active_sessions_store.set_session(device_id, session_state, expiry_seconds=24*60*60)
        #     logger.info(f"Updated viewer count for device {device_id} due to disconnect of SID {sid}.")
        pass # Placeholder for any per-device cleanup on viewer disconnect

    # Flask-SocketIO automatically handles removing SID from rooms it joined.
    # socketio_session is automatically cleaned up for this SID.
