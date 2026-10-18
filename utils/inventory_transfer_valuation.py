"""Carry actual FIFO layers through branch transfers; never invent legacy costs."""
from sqlalchemy import inspect, update
from extensions import db
from models.inventory_lot import InventoryLot
from models.stock_operations import StockTransferCostLayer
from utils.inventory_lots import _lot_query


class TransferValuationError(ValueError):
    pass


def layers(transfer_id, line_id, phase="send", kind="branch"):
    if not inspect(db.session.connection()).has_table(StockTransferCostLayer.__tablename__):
        return []
    return StockTransferCostLayer.query.execution_options(skip_branch_scope=True).filter_by(
        transfer_kind=kind, transfer_id=transfer_id, line_id=line_id, phase=phase).order_by(
        StockTransferCostLayer.sequence).all()


def apply(transfer, line, phase, product, destination):
    from utils.branch_stock_service import get_branch_stock
    from utils.product_color_service import get_branch_product_colors
    from modules.stock_operations.schema import ensure_schema
    ensure_schema()
    color=(line.variant_color or "").strip() or None
    source=product.id
    if color:
        from routes.stock_transfers import _branch_color_product_id
        source=_branch_color_product_id(transfer.from_branch_id, product.id, color)
    original=layers(transfer.id,line.id)
    if phase=="send":
        if original:
            raise TransferValuationError("طبقات التحويل موجودة؛ راجع حالة السند قبل إرساله")
        if not inspect(db.session.connection()).has_table(InventoryLot.__tablename__):
            raise TransferValuationError("راجع أساس كلفة المخزون من الجرد قبل إرسال التحويل")
        lots=_lot_query(source,transfer.from_branch_id,color).with_for_update().populate_existing().all()
        physical=next((row['qty'] for row in get_branch_product_colors(source,transfer.from_branch_id) if row['name']==color),0) if color else get_branch_stock(transfer.from_branch_id,source)
        if sum(int(lot.remaining_quantity) for lot in lots)!=physical:
            raise TransferValuationError("طبقات الكلفة لا تطابق رصيد المصدر؛ راجع أساس التقييم في الجرد قبل التحويل")
        if any(lot.unit_cost<0 for lot in lots):raise TransferValuationError("كلفة دفعة مخزون غير صالحة؛ راجع التقييم")
        remaining=int(line.quantity)
        for sequence,lot in enumerate(lots):
            take=min(remaining,int(lot.remaining_quantity))
            if not take:continue
            changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
                InventoryLot.remaining_quantity==lot.remaining_quantity).values(
                remaining_quantity=InventoryLot.remaining_quantity-take).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise TransferValuationError("تغيرت طبقات المخزون؛ حدّث السند وأعد المحاولة")
            db.session.expire(lot)
            db.session.add(StockTransferCostLayer(transfer_kind="branch",transfer_id=transfer.id,
                line_id=line.id,phase=phase,sequence=sequence,branch_id=transfer.from_branch_id,
                product_id=source,lot_id=lot.id,quantity=take,unit_cost=int(lot.unit_cost)))
            remaining-=take
            if not remaining:break
        if remaining:raise TransferValuationError("كلفة الكمية المطلوبة غير مغطاة؛ لم يرسل التحويل")
        db.session.flush()
        return layers(transfer.id,line.id)
    if not original or sum(row.quantity for row in original)!=line.quantity:
        raise TransferValuationError("هذا تحويل قديم بلا كلفة نقل موثقة؛ راجع التحويل وأساس المخزون قبل الاستلام أو الإلغاء")
    if layers(transfer.id,line.id,phase):raise TransferValuationError("مرحلة كلفة التحويل مسجلة مسبقاً")
    for row in original:
        if phase=="receive":
            source_lot=db.session.get(InventoryLot,row.lot_id)
            if not source_lot:raise TransferValuationError("دفعة الكلفة الأصلية غير موجودة؛ راجع التحويل")
            lot=InventoryLot(product_id=destination.id,branch_id=transfer.to_branch_id,
                variant_color=color,quantity=row.quantity,remaining_quantity=row.quantity,
                unit_cost=row.unit_cost,created_at=source_lot.created_at)
            db.session.add(lot);db.session.flush()
        elif phase=="cancel":
            lot=db.session.get(InventoryLot,row.lot_id)
            if not lot or lot.product_id!=source or lot.branch_id!=transfer.from_branch_id:
                raise TransferValuationError("مصدر الكلفة تغير؛ لم يُلغَ التحويل")
            if lot.remaining_quantity+row.quantity>lot.quantity:
                raise TransferValuationError("طبقات المصدر تغيرت بعد الإرسال؛ راجع التقييم")
            changed=db.session.execute(update(InventoryLot).where(InventoryLot.id==lot.id,
                InventoryLot.remaining_quantity==lot.remaining_quantity).values(
                remaining_quantity=InventoryLot.remaining_quantity+row.quantity).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise TransferValuationError("تغيرت طبقات المصدر؛ حدّث السند")
            db.session.expire(lot)
        else:raise TransferValuationError("مرحلة التحويل غير صالحة")
        db.session.add(StockTransferCostLayer(transfer_kind="branch",transfer_id=transfer.id,line_id=line.id,
            phase=phase,sequence=row.sequence,branch_id=transfer.to_branch_id if phase=="receive" else transfer.from_branch_id,
            product_id=lot.product_id,lot_id=lot.id,quantity=row.quantity,unit_cost=row.unit_cost))
    db.session.flush()
    return layers(transfer.id,line.id,phase)


def valuation_branch_ids():
    """Match report ownership: sender owns transit until receipt; jobs read their tenant."""
    from flask import g,has_request_context,session
    if not has_request_context() or not getattr(g,'branch_scope_ready',False) or not getattr(g,'independent_branches_enabled',True):
        return None
    public_id=getattr(g,'public_branch_id',None)
    if public_id:return [int(public_id)]
    if not session.get('user_id'):return None
    from utils.branch_scope import allowed_branch_ids,viewing_all_branches
    return None if viewing_all_branches() else allowed_branch_ids()


def in_transit_value():
    from modules.inventory_locations.valuation import in_transit_value as storage_value
    branch_ids=valuation_branch_ids()
    total=storage_value(branch_ids)
    if not inspect(db.session.connection()).has_table(StockTransferCostLayer.__tablename__):return total
    return total+sum(in_transit_by_sender(branch_ids).values())


def in_transit_by_sender(branch_ids=None):
    """{sender branch id: value} of goods sent and not yet settled (sent, or the remainder of a partial receipt)."""
    from models.branch import StockTransfer
    if not inspect(db.session.connection()).has_table(StockTransferCostLayer.__tablename__):return {}
    query=db.session.query(StockTransfer.from_branch_id,StockTransferCostLayer.phase,
        StockTransferCostLayer.quantity,StockTransferCostLayer.unit_cost).join(
        StockTransfer,StockTransfer.id==StockTransferCostLayer.transfer_id).filter(
        StockTransferCostLayer.transfer_kind=="branch",
        StockTransfer.status.in_(("sent","partially_received")))
    if branch_ids is not None:query=query.filter(StockTransfer.from_branch_id.in_(branch_ids))
    out={}
    for sender,phase,quantity,unit_cost in query.all():
        sign=1 if phase=="send" else -1  # receive / late / return layers settle part of what was sent
        out[sender]=out.get(sender,0)+sign*quantity*unit_cost
    return out

