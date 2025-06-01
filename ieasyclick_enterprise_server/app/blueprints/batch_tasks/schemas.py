#!/bin/python
from marshmallow import Schema, fields, validate, ValidationError

# Custom validator for a list of strings (e.g., device_ids)
def list_of_strings(data):
    if not isinstance(data, list):
        raise ValidationError("Must be a list.")
    if not all(isinstance(item, str) for item in data):
        raise ValidationError("All items in the list must be strings.")
    if not data: # Ensure list is not empty
        raise ValidationError("List cannot be empty.")

class TaskDefinitionSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=150))
    description = fields.String(allow_none=True) # Optional
    script_body = fields.String(required=True, validate=validate.Length(min=1))
    # For superadmin creating/updating a task def for a specific tenant
    tenant_id_for_super_admin = fields.Integer(allow_none=True) # Optional, only used by superadmin

class TaskAssignmentSchema(Schema):
    task_definition_id = fields.Integer(required=True, strict=True) # strict=True ensures it is an int
    device_ids = fields.List(fields.String(), required=True, validate=list_of_strings) # List of device external IDs
    # scheduled_at can be an ISO datetime string, Marshmallow can handle basic parsing to datetime if needed,
    # but often it is kept as string and parsed in the route if specific logic is applied.
    # For now, let it be a string, route can parse if necessary.
    scheduled_at = fields.String(allow_none=True, validate=validate.Regexp(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$",
        error="Invalid ISO 8601 datetime format for scheduled_at."
    )) # Basic ISO 8601 regex

class TaskAssignmentStatusUpdateSchema(Schema):
    status = fields.String(required=True, validate=validate.OneOf(["pending", "running", "completed", "failed", "cancelled"]))
    result_output = fields.String(allow_none=True)
