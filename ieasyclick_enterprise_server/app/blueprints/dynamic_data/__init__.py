#!/bin/python
from flask import Blueprint

bp = Blueprint("dynamic_data", __name__)

from . import routes
