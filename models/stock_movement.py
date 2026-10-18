from datetime import datetime

from extensions import db


class StockMovement(db.Model):
    """Immutable, idempotent record of one physical inventory mutation."""

    __tablename__ = "stock_movement"

    id = db.Column(db.Integer, primary_key=True)
    movement_key = db.Column(db.String(255), nullable=False, unique=True, index=True)
    movement_type = db.Column(db.String(50), nullable=False, index=True)
    direction = db.Column(db.String(10), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Integer, nullable=False, default=0)
    total_cost = db.Column(db.Integer, nullable=False, default=0)
    source_type = db.Column(db.String(50), nullable=False, index=True)
    source_id = db.Column(db.Integer, nullable=False, index=True)
    source_line_id = db.Column(db.Integer, nullable=True, index=True)
    reversal_of_key = db.Column(db.String(255), nullable=True, index=True)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    product = db.relationship("Product", lazy=True)
    branch = db.relationship("Branch", lazy=True)

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_stock_movement_positive_quantity"),
        db.CheckConstraint("direction IN ('in', 'out')", name="ck_stock_movement_direction"),
    )
