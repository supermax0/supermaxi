from datetime import datetime
import pytz
from flask_sqlalchemy import SQLAlchemy
from extensions import db

def get_iraq_time():
    tz = pytz.timezone('Asia/Baghdad')
    return datetime.now(tz)

class InvoiceTemplate(db.Model):
    __tablename__ = 'invoice_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_premium = db.Column(db.Boolean, default=False)
    price = db.Column(db.Integer, default=0) # in Iraqi Dinars usually
    html_file_name = db.Column(db.String(100), nullable=False) # e.g. "classic.html"
    thumbnail_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=get_iraq_time)

class TenantTemplatePurchase(db.Model):
    __tablename__ = 'tenant_template_purchases'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('invoice_templates.id'), nullable=False)
    purchase_date = db.Column(db.DateTime, default=get_iraq_time)
    amount_paid = db.Column(db.Integer, nullable=False, default=0)
    
    # Zain Cash specific fields
    status = db.Column(db.String(20), default='pending') # pending, approved, rejected
    reference_number = db.Column(db.String(100), nullable=True)
    receipt_image = db.Column(db.String(255), nullable=True)
    
    # Relationships
    tenant = db.relationship('User', foreign_keys=[tenant_id])
    template = db.relationship('InvoiceTemplate', foreign_keys=[template_id])

class TenantTemplateSettings(db.Model):
    __tablename__ = 'tenant_template_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    active_template_id = db.Column(db.Integer, db.ForeignKey('invoice_templates.id'), nullable=True)
    
    primary_color = db.Column(db.String(20), default='#2563eb')
    secondary_color = db.Column(db.String(20), default='#4a5568')
    custom_css = db.Column(db.Text, nullable=True)
    
    updated_at = db.Column(db.DateTime, default=get_iraq_time, onupdate=get_iraq_time)
    
    # Relationships
    tenant = db.relationship('User', foreign_keys=[tenant_id])
    active_template = db.relationship('InvoiceTemplate', foreign_keys=[active_template_id])
