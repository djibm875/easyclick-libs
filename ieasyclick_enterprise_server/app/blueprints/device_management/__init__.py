from flask import Blueprint

bp = Blueprint('device_management', __name__)

from . import routes
