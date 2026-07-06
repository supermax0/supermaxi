#!/usr/bin/env python3
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from app import app
from flask import g
from models.employee import Employee

with app.app_context():
    g.tenant = "super"
    rows = Employee.query.filter(Employee.username.ilike("admin")).all()
    print("ADMIN_USERS=", [(e.id, e.username, e.role, e.is_active) for e in rows])
