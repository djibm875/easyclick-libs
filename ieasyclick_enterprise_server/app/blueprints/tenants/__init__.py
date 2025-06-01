#!/bin/python
from flask import Blueprint

bp = Blueprint("tenants", __name__)

from . import routes
