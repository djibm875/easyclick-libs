#!/bin/python
import json
from app.models import User, Tenant, Device, TaskDefinition, TaskAssignment
from app import db # To directly query DB for verification

# Fixtures like test_client, init_database are in conftest.py

def test_full_tenant_workflow(test_client, init_database):
    """
    Tests a full workflow:
    1. User Registration (Tenant Creation)
    2. User Login
    3. Device Registration (with API Key generation)
    4. Task Definition Creation
    5. Task Assignment
    """
    # --- 1. User Registration ---
    user_data = {
        "username": "workflowuser",
        "email": "workflow@example.com",
        "password": "Password123!",
        "tenant_name": "WorkflowTenant"
    }
    reg_response = test_client.post("/auth/register", json=user_data)
    assert reg_response.status_code == 201
    reg_data = reg_response.json
    assert reg_data["username"] == user_data["username"]
    user_id = reg_data["id"]

    # Verify user and tenant in DB
    user_in_db = db.session.get(User, user_id)
    assert user_in_db is not None
    assert user_in_db.email == user_data["email"]
    assert user_in_db.tenant is not None
    assert user_in_db.tenant.name == user_data["tenant_name"]
    tenant_id = user_in_db.tenant_id

    # --- 2. User Login ---
    login_response = test_client.post("/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"]
    })
    assert login_response.status_code == 200
    # The test_client handles cookies, so the session is now active for subsequent requests.

    # --- 3. Device Registration ---
    device_payload = {
        "device_id": "workflow_device_001", # External ID
        "platform": "Android",
        "device_name": "Workflow Test Device"
    }
    # User is logged in, so this device will be associated with their tenant
    device_reg_response = test_client.post("/api/devices/register", json=device_payload)
    assert device_reg_response.status_code == 201
    device_reg_data = device_reg_response.json
    assert device_reg_data["device_id"] == device_payload["device_id"]
    assert "api_key" in device_reg_data
    assert device_reg_data["api_key"] is not None
    device_api_key = device_reg_data["api_key"] # Save for later (e.g. API key usage test)
    internal_device_id = device_reg_data["id"] # Internal PK

    # Verify device in DB
    device_in_db = db.session.get(Device, internal_device_id)
    assert device_in_db is not None
    assert device_in_db.tenant_id == tenant_id
    assert device_in_db.api_key == device_api_key

    # --- 4. Task Definition Creation ---
    task_def_payload = {
        "name": "Workflow Task Def",
        "description": "A task definition for the workflow test",
        "script_body": "echo \"Hello Workflow\""
        # tenant_id is implicitly current_user.tenant_id
    }
    task_def_response = test_client.post("/api/tasks/definitions", json=task_def_payload)
    assert task_def_response.status_code == 201
    task_def_data = task_def_response.json
    assert task_def_data["name"] == task_def_payload["name"]
    task_def_id = task_def_data["id"]

    # Verify task definition in DB
    task_def_in_db = db.session.get(TaskDefinition, task_def_id)
    assert task_def_in_db is not None
    assert task_def_in_db.tenant_id == tenant_id

    # --- 5. Task Assignment ---
    assign_payload = {
        "task_definition_id": task_def_id,
        "device_ids": [device_payload["device_id"]] # List of external device IDs
        # "scheduled_at" can be omitted to use default (now)
    }
    assign_response = test_client.post("/api/tasks/assign", json=assign_payload)
    assert assign_response.status_code == 201 # All assignments should succeed
    assign_data = assign_response.json
    assert len(assign_data["assignments_created"]) == 1
    assert not assign_data["errors"] # No errors

    assignment_created = assign_data["assignments_created"][0]
    assert assignment_created["task_definition_id"] == task_def_id
    assert assignment_created["device_external_id"] == device_payload["device_id"]
    assert assignment_created["status"] == "pending"
    assignment_id = assignment_created["id"]

    # Verify task assignment in DB
    assignment_in_db = db.session.get(TaskAssignment, assignment_id)
    assert assignment_in_db is not None
    assert assignment_in_db.task_definition_id == task_def_id
    assert assignment_in_db.device_id == internal_device_id # Check internal device PK

    # --- (Optional) Logout ---
    logout_response = test_client.post("/auth/logout")
    assert logout_response.status_code == 200

def test_tenant_isolation(test_client, init_database):
    """
    Tests tenant isolation:
    1. Create User A in Tenant A, User B in Tenant B.
    2. User A creates resources (device, task definition).
    3. Verify User B cannot access/modify User A resources.
    4. Verify Super Admin can access resources from both tenants (optional extension).
    """
    # --- Setup: User A in Tenant A ---
    user_a_data = {"username": "usera", "email": "usera@example.com", "password": "PasswordA123!", "tenant_name": "TenantA"}
    reg_a_response = test_client.post("/auth/register", json=user_a_data)
    assert reg_a_response.status_code == 201
    user_a_id = reg_a_response.json["id"]

    # Login User A
    login_a_response = test_client.post("/auth/login", json={"username": "usera", "password": "PasswordA123!"})
    assert login_a_response.status_code == 200
    # Subsequent requests by test_client are now as User A

    # User A registers Device A1
    device_a1_payload = {"device_id": "device_A1", "platform": "iOS", "device_name": "UserA_Device1"}
    device_a1_reg_response = test_client.post("/api/devices/register", json=device_a1_payload)
    assert device_a1_reg_response.status_code == 201
    device_a1_internal_id = device_a1_reg_response.json["id"]
    device_a1_api_key = device_a1_reg_response.json["api_key"]

    # User A creates Task Definition A1
    task_def_a1_payload = {"name": "TaskDef_A1", "script_body": "echo TaskA1"}
    task_def_a1_response = test_client.post("/api/tasks/definitions", json=task_def_a1_payload)
    assert task_def_a1_response.status_code == 201
    task_def_a1_id = task_def_a1_response.json["id"]

    # Logout User A
    test_client.post("/auth/logout")

    # --- Setup: User B in Tenant B ---
    user_b_data = {"username": "userb", "email": "userb@example.com", "password": "PasswordB123!", "tenant_name": "TenantB"}
    reg_b_response = test_client.post("/auth/register", json=user_b_data)
    assert reg_b_response.status_code == 201
    user_b_id = reg_b_response.json["id"]

    # Login User B
    login_b_response = test_client.post("/auth/login", json={"username": "userb", "password": "PasswordB123!"})
    assert login_b_response.status_code == 200
    # Subsequent requests by test_client are now as User B

    # User B registers Device B1 (their own device)
    device_b1_payload = {"device_id": "device_B1", "platform": "Android", "device_name": "UserB_Device1"}
    device_b1_reg_response = test_client.post("/api/devices/register", json=device_b1_payload)
    assert device_b1_reg_response.status_code == 201
    device_b1_internal_id = device_b1_reg_response.json["id"]


    # --- Verification: User B attempts to access User A resources ---

    # 1. List Devices (User B should not see Device A1)
    list_devices_b_response = test_client.get("/api/devices/")
    assert list_devices_b_response.status_code == 200
    devices_seen_by_b = [d["device_id"] for d in list_devices_b_response.json["devices"]]
    assert device_a1_payload["device_id"] not in devices_seen_by_b
    assert device_b1_payload["device_id"] in devices_seen_by_b # Should see their own

    # 2. Get Device A1 details
    get_device_a1_b_response = test_client.get(f"/api/devices/{device_a1_payload['device_id']}")
    assert get_device_a1_b_response.status_code == 403 # Forbidden (or 404 if we hide existence)

    # 3. Update Device A1
    update_device_a1_b_response = test_client.put(f"/api/devices/{device_a1_payload['device_id']}", json={"device_name": "UpdatedByB"})
    assert update_device_a1_b_response.status_code == 403

    # 4. Delete Device A1
    delete_device_a1_b_response = test_client.delete(f"/api/devices/{device_a1_payload['device_id']}")
    assert delete_device_a1_b_response.status_code == 403

    # Verify Device A1 still exists (owned by Tenant A)
    # (Need to login as User A or SuperAdmin to verify this part robustly, or check DB directly for test simplicity)
    device_a1_in_db = db.session.get(Device, device_a1_internal_id)
    assert device_a1_in_db is not None


    # 5. List Task Definitions (User B should not see TaskDef A1)
    list_task_defs_b_response = test_client.get("/api/tasks/definitions")
    assert list_task_defs_b_response.status_code == 200
    task_defs_seen_by_b = [td["name"] for td in list_task_defs_b_response.json]
    assert task_def_a1_payload["name"] not in task_defs_seen_by_b

    # 6. Get Task Definition A1 details
    get_task_def_a1_b_response = test_client.get(f"/api/tasks/definitions/{task_def_a1_id}")
    assert get_task_def_a1_b_response.status_code == 403

    # 7. Update Task Definition A1
    update_task_def_a1_b_response = test_client.put(f"/api/tasks/definitions/{task_def_a1_id}", json={"description": "UpdatedByB"})
    assert update_task_def_a1_b_response.status_code == 403

    # 8. Delete Task Definition A1
    delete_task_def_a1_b_response = test_client.delete(f"/api/tasks/definitions/{task_def_a1_id}")
    assert delete_task_def_a1_b_response.status_code == 403

    # Verify TaskDef A1 still exists
    task_def_a1_in_db = db.session.get(TaskDefinition, task_def_a1_id)
    assert task_def_a1_in_db is not None


    # 9. Assign Task Definition A1 to User B Device B1
    assign_a1_to_b1_payload = {"task_definition_id": task_def_a1_id, "device_ids": [device_b1_payload["device_id"]]}
    assign_a1_to_b1_response = test_client.post("/api/tasks/assign", json=assign_a1_to_b1_payload)
    # This should fail because User B cannot access/use TaskDef A1
    assert assign_a1_to_b1_response.status_code == 403
    # Or if the check is on device belonging to task_def tenant, it could be a different error if task_def is not found first.
    # Current logic: "Access to use this task definition is forbidden" -> 403

    # --- (Optional) Verification: User A attempts to access User B resources ---
    # Logout User B, Login User A
    test_client.post("/auth/logout")
    test_client.post("/auth/login", json={"username": "usera", "password": "PasswordA123!"})

    get_device_b1_a_response = test_client.get(f"/api/devices/{device_b1_payload['device_id']}")
    assert get_device_b1_a_response.status_code == 403

    # Logout User A
    test_client.post("/auth/logout")

def test_device_api_key_usage(test_client, init_database):
    """
    Tests the usage of API keys for device-specific endpoints:
    1. Register a user and a device to get an API key.
    2. Test /api/devices/heartbeat with valid/invalid/missing API key.
    3. Test /api/data/submit with valid/invalid/missing API key.
    """
    # --- Setup: User and Device Registration ---
    user_data = {"username": "apikeyuser", "email": "apikey@example.com", "password": "PasswordApi123!", "tenant_name": "ApiKeyTenant"}
    reg_response = test_client.post("/auth/register", json=user_data)
    assert reg_response.status_code == 201

    # Login the user to register a device
    login_response = test_client.post("/auth/login", json={"username": "apikeyuser", "password": "PasswordApi123!"})
    assert login_response.status_code == 200

    device_payload = {"device_id": "device_apikey_001", "platform": "System", "device_name": "API Key Test Device"}
    device_reg_response = test_client.post("/api/devices/register", json=device_payload)
    assert device_reg_response.status_code == 201
    device_reg_data = device_reg_response.json
    actual_device_id = device_reg_data["device_id"] # This is the external ID
    api_key = device_reg_data["api_key"]
    assert api_key is not None

    # Logout user, as device calls are not typically tied to a user session directly
    test_client.post("/auth/logout")

    # --- Test /api/devices/heartbeat ---
    heartbeat_payload = {"device_id": actual_device_id, "status": "testing_heartbeat"}

    # Case 1: Valid API Key
    hb_valid_response = test_client.post("/api/devices/heartbeat",
                                         headers={"X-API-Key": api_key},
                                         json=heartbeat_payload)
    assert hb_valid_response.status_code == 200
    assert hb_valid_response.json["status"] == "testing_heartbeat"

    # Case 2: Invalid API Key
    hb_invalid_key_response = test_client.post("/api/devices/heartbeat",
                                               headers={"X-API-Key": "invalidkey123"},
                                               json=heartbeat_payload)
    assert hb_invalid_key_response.status_code == 403 # Forbidden

    # Case 3: Missing API Key header
    hb_missing_key_response = test_client.post("/api/devices/heartbeat", json=heartbeat_payload)
    assert hb_missing_key_response.status_code == 401 # Unauthorized

    # Case 4: Correct API Key, but for a different (non-existent) device_id in payload
    hb_wrong_device_payload = {"device_id": "non_existent_device", "status": "testing_heartbeat"}
    hb_wrong_device_response = test_client.post("/api/devices/heartbeat",
                                                headers={"X-API-Key": api_key}, # Valid key for actual_device_id
                                                json=hb_wrong_device_payload)
    assert hb_wrong_device_response.status_code == 404 # Device not registered (server looks up by payload device_id first)


    # --- Test /api/data/submit ---
    data_submission_payload = {
        "device_id": actual_device_id,
        "data_type": "test_metric",
        "payload": {"value": 123, "unit": "tests"}
    }

    # Case 1: Valid API Key
    ds_valid_response = test_client.post("/api/data/submit",
                                         headers={"X-API-Key": api_key},
                                         json=data_submission_payload)
    assert ds_valid_response.status_code == 201
    assert ds_valid_response.json["data_type"] == "test_metric"
    assert ds_valid_response.json["data_payload"]["value"] == 123

    # Case 2: Invalid API Key
    ds_invalid_key_response = test_client.post("/api/data/submit",
                                               headers={"X-API-Key": "invalidkey123"},
                                               json=data_submission_payload)
    assert ds_invalid_key_response.status_code == 403

    # Case 3: Missing API Key header
    ds_missing_key_response = test_client.post("/api/data/submit", json=data_submission_payload)
    assert ds_missing_key_response.status_code == 401

    # Case 4: Correct API Key, but for a different (non-existent) device_id in payload
    ds_wrong_device_payload = {**data_submission_payload, "device_id": "non_existent_device_for_data"}
    ds_wrong_device_response = test_client.post("/api/data/submit",
                                                headers={"X-API-Key": api_key},
                                                json=ds_wrong_device_payload)
    assert ds_wrong_device_response.status_code == 404 # Device not found based on payload
