from sqlalchemy import inspect
from extensions import db
from models.product import Product
from models.inventory_lot import InventoryLot
from models.stock_operations import StockTransferCostLayer
from utils.inventory_transfer_valuation import layers


def unit_cost(transfer,line,phase):
    """Warehouse ledger uses its existing unit-cost basis, fixed at dispatch."""
    InventoryLot.__table__.create(bind=db.session.connection(),checkfirst=True)
    from modules.stock_operations.schema import ensure_schema
    ensure_schema()
    proof=layers(transfer.id,line.id,kind='warehouse')
    if phase=='send':
        if proof:raise ValueError("كلفة التحويل مسجلة؛ راجع حالة السند")
        product=Product.query.execution_options(skip_branch_scope=True).filter_by(id=line.product_id).first()
        if not product:raise ValueError("صنف التحويل غير موجود")
        cost=int(product.buy_price or 0)
        if cost<0:raise ValueError("كلفة صنف المخزن غير صالحة")
    else:
        if len(proof)!=1 or proof[0].quantity!=line.quantity:
            raise ValueError("التحويل القديم يحتاج مراجعة كلفته قبل الاستلام أو الإلغاء")
        cost=proof[0].unit_cost
    from modules.wholesale.models.warehouse import Warehouse
    place=db.session.get(Warehouse,transfer.to_warehouse_id if phase=='receive' else transfer.from_warehouse_id)
    db.session.add(StockTransferCostLayer(transfer_kind='warehouse',transfer_id=transfer.id,line_id=line.id,
        phase=phase,sequence=0,branch_id=place.branch_id,product_id=line.product_id,lot_id=None,
        quantity=line.quantity,unit_cost=cost))
    db.session.flush()
    return cost

