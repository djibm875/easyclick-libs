#!/bin/python
from flask import Blueprint

bp = Blueprint("screen_mirroring", __name__)

from . import routes
from . import events # Ensure events are imported so handlers are registered
