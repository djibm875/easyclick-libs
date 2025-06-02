#!/bin/python
from marshmallow import Schema, fields, validate

class DeviceRegistrationSchema(Schema):
    device_id = fields.String(required=True, validate=validate.Length(min=1, max=255))
    platform = fields.String(required=True, validate=validate.Length(min=1, max=50))
    device_name = fields.String(validate=validate.Length(max=100), allow_none=True)
    os_version = fields.String(validate=validate.Length(max=50), allow_none=True)

class DeviceUpdateSchema(Schema):
    device_name = fields.String(validate=validate.Length(max=100), allow_none=True)
    os_version = fields.String(validate=validate.Length(max=50), allow_none=True)
    status = fields.String(validate=validate.OneOf(["online", "offline", "busy"]), allow_none=True)
    platform = fields.String(validate=validate.Length(min=1, max=50), allow_none=True)

# New schema for device updating its task status
class DeviceTaskStatusUpdateSchema(Schema):
    status = fields.String(required=True, validate=validate.OneOf(["running", "completed", "failed", "cancelled"])) # Device can report these
    result_output = fields.String(allow_none=True) # Optional result output from the script/task
