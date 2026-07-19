"""Run the stale-product regression against a disposable tenant database copy."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    tenant = os.environ.get("FINORA_REGRESSION_TENANT", "")
    if not tenant:
        raise SystemExit("FINORA_REGRESSION_TENANT is required")

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.invoice import Invoice
    from models.product import Product
    from modules.ai_sales.engine import process_inbound_message
    from modules.ai_sales.models import AISalesConversation, AISalesMessage

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        conversation = AISalesConversation.query.get(875)
        if not conversation:
            raise SystemExit("Conversation 875 was not found in the disposable copy")
        cooler = Product.query.filter(Product.name.contains("براد كهرمانه")).first()
        washer = Product.query.filter(Product.name.contains("غساله دنكا 16")).first()
        screen = Product.query.filter(Product.name.contains("شاشه")).first()
        if not all((cooler, washer, screen)):
            raise SystemExit("Required regression products were not found")

        context = conversation.get_context()
        context.update({
            "product_family": "screen",
            "last_product_ids": [screen.id],
            "focus_product_id": screen.id,
            "pending_order": {
                "product_id": washer.id,
                "product_name": washer.name,
                "unit_price": int(washer.sale_price or 0),
            },
        })
        context.pop("purchase_selection", None)
        context.pop("created_order_id", None)
        conversation.sales_stage = "waiting_confirmation"
        conversation.set_context(context)
        invoice_count_before = Invoice.query.count()
        marker = uuid.uuid4().hex

        switch_message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=conversation.channel_account_id,
            external_message_id=f"regression-switch-{marker}",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="براد كهرمانه",
            status="received",
        )
        db.session.add(switch_message)
        db.session.commit()
        process_inbound_message(switch_message.id, send_external=False)

        price_message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=conversation.channel_account_id,
            external_message_id=f"regression-price-{marker}",
            direction="inbound",
            sender_type="customer",
            message_type="text",
            text_content="سعره بي مجال",
            status="received",
        )
        db.session.add(price_message)
        db.session.commit()
        reply = process_inbound_message(price_message.id, send_external=False)

        voice_message = AISalesMessage(
            conversation_id=conversation.id,
            channel_account_id=conversation.channel_account_id,
            external_message_id=f"regression-voice-{marker}",
            direction="inbound",
            sender_type="customer",
            message_type="audio",
            transcription="سعره بي مجال",
            status="received",
        )
        db.session.add(voice_message)
        db.session.commit()
        voice_reply = process_inbound_message(voice_message.id, send_external=False)
        duplicate_result = process_inbound_message(voice_message.id, send_external=False)
        generated_voice = AISalesMessage.query.filter(
            AISalesMessage.conversation_id == conversation.id,
            AISalesMessage.direction == "outbound",
            AISalesMessage.message_type == "audio",
            AISalesMessage.id > voice_message.id,
        ).order_by(AISalesMessage.id.desc()).first()

        final_context = conversation.get_context()
        result = {
            "product_family": final_context.get("product_family"),
            "focus_product_id": final_context.get("focus_product_id"),
            "cooler_product_id": cooler.id,
            "pending_order": final_context.get("pending_order"),
            "purchase_selection": final_context.get("purchase_selection"),
            "invoice_count_delta": Invoice.query.count() - invoice_count_before,
            "reply": reply.text_content if reply else "",
            "voice_text_reply": voice_reply.text_content if voice_reply else "",
            "voice_generated": bool(generated_voice and generated_voice.media_path),
            "duplicate_processing_blocked": duplicate_result is None,
        }
        assert result["product_family"] == "air_cooler", result
        assert result["focus_product_id"] == cooler.id, result
        assert not result["pending_order"], result
        assert not result["purchase_selection"], result
        assert result["invoice_count_delta"] == 0, result
        assert "براد كهرمانه" in result["reply"], result
        assert "غساله" not in result["reply"], result
        assert result["voice_generated"], result
        assert result["duplicate_processing_blocked"], result
        print(json.dumps(result, ensure_ascii=False), flush=True)
        os._exit(0)


if __name__ == "__main__":
    main()
