# models/page.py
from extensions import db
from datetime import datetime

# جدول ارتباط many-to-many بين Employee و Page
employee_pages = db.Table('employee_pages',
    db.Column('employee_id', db.Integer, db.ForeignKey('employee.id'), primary_key=True),
    db.Column('page_id', db.Integer, db.ForeignKey('page.id'), primary_key=True)
)

class Page(db.Model):
    __tablename__ = "page"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    visible_to_cashier = db.Column(db.Boolean, default=True)  # مرئي للكاشير
    visible_to_admin = db.Column(db.Boolean, default=True)  # مرئي للأدمن
    
    # علاقة many-to-many مع الموظفين
    employees = db.relationship(
        'Employee',
        secondary=employee_pages,
        backref=db.backref('pages', lazy='dynamic'),
        lazy='dynamic'
    )
    
    # علاقة مع الفواتير
    invoices = db.relationship(
        'Invoice',
        backref='page',
        lazy=True
    )
    
    def __repr__(self):
        return f"<Page {self.name}>"
    
    def get_orders_count(self):
        """حساب عدد الطلبات للبيج"""
        from models.invoice import Invoice
        return Invoice.query.filter_by(page_id=self.id).count()
