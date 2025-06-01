#!/bin/python
import json
import logging
from app import redis_client # Import the globally configured redis_client from app/__init__.py

logger = logging.getLogger(__name__)

class RedisSessionStore:
    def __init__(self, client, prefix="session:screenmirror:"):
        """
        Initializes the RedisSessionStore.
        :param client: An instance of a Redis client (e.g., redis.Redis).
        :param prefix: Prefix for all keys stored in Redis for this store.
        """
        if client is None:
            logger.critical("RedisSessionStore initialized with a None Redis client. This will fail.")
            # This should ideally not happen if app/__init__.py exits on Redis connection failure.
            raise ValueError("Redis client cannot be None for RedisSessionStore.")
        self.client = client
        self.prefix = prefix
        logger.info(f"RedisSessionStore initialized with prefix \"{prefix}\".")

    def _key(self, session_id: str) -> str:
        """Helper to construct the full Redis key."""
        return f"{self.prefix}{session_id}"

    def set_session(self, session_id: str, data: dict, expiry_seconds: int = None):
        """
        Stores session data in Redis.
        :param session_id: The unique ID for the session (e.g., device_id).
        :param data: The session data dictionary.
        :param expiry_seconds: Optional. How long until the session expires (in seconds).
                               If None, session does not expire (or uses Redis default if any).
        """
        try:
            key = self._key(session_id)
            value = json.dumps(data) # Serialize data to JSON string
            if expiry_seconds and expiry_seconds > 0:
                self.client.setex(key, expiry_seconds, value)
            else:
                self.client.set(key, value)
            logger.debug(f"Session {session_id} set in Redis with expiry {expiry_seconds}s.")
        except Exception as e:
            logger.error(f"Error setting session {session_id} in Redis: {e}", exc_info=True)
            # Depending on requirements, might re-raise or handle gracefully.

    def get_session(self, session_id: str) -> dict | None:
        """
        Retrieves session data from Redis.
        :param session_id: The unique ID for the session.
        :return: The session data dictionary, or None if not found.
        """
        try:
            key = self._key(session_id)
            value_json = self.client.get(key)
            if value_json:
                logger.debug(f"Session {session_id} retrieved from Redis.")
                return json.loads(value_json) # Deserialize JSON string to dict
            else:
                logger.debug(f"Session {session_id} not found in Redis.")
                return None
        except Exception as e:
            logger.error(f"Error getting session {session_id} from Redis: {e}", exc_info=True)
            return None

    def delete_session(self, session_id: str) -> bool:
        """
        Deletes session data from Redis.
        :param session_id: The unique ID for the session.
        :return: True if deleted, False if not found or error.
        """
        try:
            key = self._key(session_id)
            deleted_count = self.client.delete(key)
            if deleted_count > 0:
                logger.info(f"Session {session_id} deleted from Redis.")
                return True
            else:
                logger.debug(f"Session {session_id} to delete was not found in Redis.")
                return False
        except Exception as e:
            logger.error(f"Error deleting session {session_id} from Redis: {e}", exc_info=True)
            return False

# Instantiate the session store with the global redis_client.
# This shared_session_store will be imported by other modules (e.g., screen_mirroring blueprints).
# This relies on app/__init__.py successfully initializing redis_client before this module is fully imported
# by other parts of the application that might use shared_session_store.
# Python module import system usually handles this if imports are structured well.
if redis_client:
    shared_session_store = RedisSessionStore(client=redis_client)
else:
    # This case should ideally be prevented by sys.exit() in app/__init__.py if Redis fails to connect.
    # However, as a fallback or for environments where app init might not run (e.g. some test setups without full app context),
    # we log a critical error. The application might not function correctly for screen mirroring.
    logger.critical("redis_client is None when attempting to instantiate shared_session_store in session_store.py. Screen mirroring sessions will fail.")
    # Provide a dummy store to prevent import errors, but it won't work across workers.
    # This is mostly a safeguard against catastrophic import failure.
    class DummySessionStore: # Fallback if Redis is not available
        def __init__(self): logger.error("USING DUMMY SESSION STORE!")
        def set_session(self, sid, data, exp=None): logger.error("Dummy store: set_session called")
        def get_session(self, sid): logger.error("Dummy store: get_session called"); return None
        def delete_session(self, sid): logger.error("Dummy store: delete_session called"); return False
    shared_session_store = DummySessionStore()
