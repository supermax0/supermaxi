"""Migration script to add opening_stock column to product table"""
from extensions import db
from models.product import Product

def migrate():
    """Add opening_stock column to product table"""
    try:
        # Check if column already exists
        conn = db.session.connection()
        result = conn.exec_driver_sql("PRAGMA table_info(product)").fetchall()
        columns = [row[1] for row in result]
        
        if 'opening_stock' not in columns:
            print("Adding opening_stock column...")
            db.session.execute(db.text("ALTER TABLE product ADD COLUMN opening_stock INTEGER DEFAULT 0"))
            db.session.commit()
            print("✅ Column 'opening_stock' added successfully!")
            
            # Set opening_stock = quantity for existing products
            products = Product.query.all()
            for product in products:
                product.opening_stock = product.quantity
            db.session.commit()
            print(f"✅ Updated {len(products)} products with opening_stock")
        else:
            print("✅ Column 'opening_stock' already exists")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error: {e}")
        raise

if __name__ == "__main__":
    from app import app
    with app.app_context():
        migrate()
