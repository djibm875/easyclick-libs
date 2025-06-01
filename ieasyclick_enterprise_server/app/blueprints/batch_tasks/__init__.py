#!/bin/python
from flask import Blueprint

bp = Blueprint("batch_tasks", __name__)

from . import routes # Will create routes.py next
