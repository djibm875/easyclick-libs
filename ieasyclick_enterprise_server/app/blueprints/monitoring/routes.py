#!/bin/python
from flask import Response, jsonify
from . import bp
from prometheus_client import CollectorRegistry, Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST
from app.models import Device, Tenant, User # To get some counts for metrics

# Create a registry for metrics
registry = CollectorRegistry()

# Define some metrics
# These will be global, so define them once when the module is loaded.
# Ensure these are not re-defined on every request.

# Gauge for total registered devices
DEVICE_COUNT = Gauge("app_devices_total", "Total number of registered devices", registry=registry)
# Gauge for total tenants
TENANT_COUNT = Gauge("app_tenants_total", "Total number of active tenants", registry=registry)
# Counter for HTTP requests (example, could be more granular)
HTTP_REQUESTS_TOTAL = Counter("app_http_requests_total", "Total HTTP Requests", ["method", "endpoint"], registry=registry)
# Gauge for active users (example, if we track sessions actively)
# ACTIVE_USERS = Gauge("app_active_users_total", "Total active users", registry=registry)


@bp.route("/metrics")
def metrics():
    """Expose application metrics in Prometheus format."""

    # Update gauge values before generating output
    # In a real app, these might be updated periodically or on events rather than every scrape.
    DEVICE_COUNT.set(Device.query.count())
    TENANT_COUNT.set(Tenant.query.count())
    # ACTIVE_USERS.set(...) # Logic to count active sessions if available

    # Example for HTTP_REQUESTS_TOTAL:
    # This counter should ideally be incremented in a request middleware or decorator.
    # For demonstration, we can increment a dummy one here, but this is not how it's typically used.
    # HTTP_REQUESTS_TOTAL.labels(method="GET", endpoint="/metrics").inc()
    # The above line in a metrics endpoint itself is not standard.
    # Counters are usually incremented when the actual events happen.

    return Response(generate_latest(registry), mimetype=CONTENT_TYPE_LATEST)

@bp.route("/health")
def health_check():
    """Basic health check endpoint."""
    # Could add checks for DB connection, etc.
    return jsonify({"status": "UP", "message": "Application is running"}), 200

# It would be better to increment HTTP_REQUESTS_TOTAL in app.before_request or similar
# For now, this is just setting up the endpoint.
