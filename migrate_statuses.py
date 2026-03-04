
from app import create_app
from extensions import db
from models.invoice import Invoice
from sqlalchemy import or_

def migrate():
    app = create_app()
    with app.app_context():
        print("Starting status migration...")
        
        # Unify Invoice statuses
        # We target status in ["ملغي", "راجع", "راجعة", "راجعه"] -> "مرتجع"
        target_statuses = ["ملغي", "راجع", "راجعة", "راجعه"]
        invoices = Invoice.query.filter(
            or_(
                Invoice.status.in_(target_statuses),
                Invoice.payment_status.in_(target_statuses)
            )
        ).all()
        
        count = 0
        for inv in invoices:
            if inv.status in target_statuses:
                inv.status = "مرتجع"
            if inv.payment_status in target_statuses:
                inv.payment_status = "مرتجع"
            count += 1
            
        db.session.commit()
        print(f"Migration complete. Updated {count} records.")

if __name__ == "__main__":
    migrate()
