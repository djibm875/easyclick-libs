#!/bin/python
from . import db
from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import secrets # Added for generating API keys
import logging # Added for logging

logger = logging.getLogger(__name__)

class Tenant(db.Model):
    __tablename__ = "tenant"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    users = db.relationship("User", backref="tenant", lazy="dynamic")
    devices = db.relationship("Device", backref="tenant", lazy="dynamic")
    task_definitions = db.relationship("TaskDefinition", backref="tenant", lazy="dynamic")
    dynamic_data_entries = db.relationship("DynamicDataEntry", backref="tenant", lazy="dynamic")

    def __repr__(self): return f"<Tenant {self.name}>"
    def to_dict(self):
        return {"id": self.id, "name": self.name,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}

class User(db.Model, UserMixin):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default="user", nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def __repr__(self): return f"<User {self.username}>"
    def to_dict(self, include_tenant=True):
        data = {"id": self.id, "username": self.username, "email": self.email, "role": self.role, "tenant_id": self.tenant_id,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}
        if include_tenant and self.tenant: data["tenant_name"] = self.tenant.name
        return data

class Device(db.Model):
    __tablename__ = "device"
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(255), unique=True, nullable=False) # External unique ID
    device_name = db.Column(db.String(100), nullable=True)
    platform = db.Column(db.String(50), nullable=False)
    os_version = db.Column(db.String(50))
    status = db.Column(db.String(50), default="offline", nullable=False)
    last_seen = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)) # Retained timezone=True
    registered_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)) # Retained timezone=True
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False)

    api_key = db.Column(db.String(64), unique=True, nullable=True, index=True) # Added: Stores the actual API key. Nullable if generated post-registration or optional. For now, let's make it non-nullable and generated at registration.
                                                                              # Changed to nullable=True to allow existing devices to not have one initially, will be set by registration.
                                                                              # Or, make nullable=False and ensure generation. For new field, nullable=True then backfill is safer.
                                                                              # Let's plan to generate it always on new registrations. So nullable=False if all new devices get one.
                                                                              # If we want to add to existing, start with nullable=True.
                                                                              # For this exercise, let's make it nullable=True for easier migration initially. It will be set for new devices.

    dynamic_data_entries = db.relationship("DynamicDataEntry", backref="device", lazy="dynamic")

    def __repr__(self): return f"<Device {self.device_id} (Tenant: {self.tenant_id})>"
    def to_dict(self): # Exclude api_key from general to_dict for security
        return {"id": self.id, "device_id": self.device_id, "device_name": self.device_name,
                "platform": self.platform, "os_version": self.os_version, "status": self.status,
                "last_seen": self.last_seen.isoformat() if self.last_seen else None,
                "registered_at": self.registered_at.isoformat() if self.registered_at else None,
                "tenant_id": self.tenant_id, "tenant_name": self.tenant.name if self.tenant else None}

    def to_dict_with_key(self): # Special method to include API key, e.g. only on registration response
        data = self.to_dict()
        data["api_key"] = self.api_key
        return data

    def generate_api_key(self):
        self.api_key = secrets.token_urlsafe(32) # Generate a 32-byte (43 char) url-safe key
        logger.info(f"Generated API key for device {self.id} (external ID: {self.device_id})")


class TaskDefinition(db.Model):
    __tablename__ = "task_definition"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    script_body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("name", "tenant_id", name="uq_taskdefinition_tenant_name"),)
    assignments = db.relationship("TaskAssignment", backref="task_definition", lazy=True, cascade="all, delete-orphan")

    def __repr__(self): return f"<TaskDefinition {self.name} (Tenant: {self.tenant_id})>"
    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description, "script_body": self.script_body,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "tenant_id": self.tenant_id, "tenant_name": self.tenant.name if self.tenant else None }

class TaskAssignment(db.Model):
    __tablename__ = "task_assignment"
    id = db.Column(db.Integer, primary_key=True)
    task_definition_id = db.Column(db.Integer, db.ForeignKey("task_definition.id"), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey("device.id"), nullable=False)
    status = db.Column(db.String(50), default="pending", nullable=False)
    scheduled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    result_output = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    device = db.relationship("Device", backref=db.backref("task_assignments", lazy="dynamic"))
    dynamic_data_entries = db.relationship("DynamicDataEntry", backref="task_assignment", lazy="dynamic")

    def __repr__(self): return f"<TaskAssignment {self.id} for TaskDef {self.task_definition_id} on Device {self.device_id} - {self.status}>"
    def to_dict(self):
        return {"id": self.id, "task_definition_id": self.task_definition_id,
                "task_name": self.task_definition.name if self.task_definition else None,
                "device_external_id": self.device.device_id if self.device else None,
                "device_internal_id": self.device_id, "status": self.status,
                "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "result_output": self.result_output,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "tenant_id": self.task_definition.tenant_id if self.task_definition else (self.device.tenant_id if self.device else None)}

class DynamicDataEntry(db.Model):
    __tablename__ = "dynamic_data_entry"
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("device.id"), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False)
    task_assignment_id = db.Column(db.Integer, db.ForeignKey("task_assignment.id"), nullable=True)
    data_type = db.Column(db.String(100), nullable=True, index=True)
    data_payload = db.Column(db.JSON, nullable=False)
    reported_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self): return f"<DynamicDataEntry {self.id} from Device {self.device_id} (Type: {self.data_type})>"
    def to_dict(self):
        return {"id": self.id,
                "device_external_id": self.device.device_id if self.device else None,
                "device_internal_id": self.device_id, "tenant_id": self.tenant_id,
                "task_assignment_id": self.task_assignment_id, "data_type": self.data_type,
                "data_payload": self.data_payload,
                "reported_at": self.reported_at.isoformat() if self.reported_at else None,
                "created_at": self.created_at.isoformat() if self.created_at else None}
