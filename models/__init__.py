from .product import Product
from .customer import Customer
from .customer_credit import CustomerCreditPlan, CustomerInstallment, CustomerCreditPayment
from .account_transaction import AccountTransaction
from .treasury_account import TreasuryAccount
from .treasury_transfer import TreasuryTransfer
from .supplier import Supplier
from .purchase import Purchase
from .purchase_item import PurchaseItem
from .purchase_payment import PurchasePayment
from .purchase_attachment import PurchaseAttachment
from .branch import Branch, BranchStock, StockTransfer, StockTransferLine
from .expense import Expense
from .maintenance_record import MaintenanceRecord
from .fixed_asset_category import FixedAssetCategory
from .fixed_asset import FixedAsset
from .fixed_asset_movement import FixedAssetMovement
from .fixed_asset_depreciation import FixedAssetDepreciation
from .fixed_asset_maintenance import FixedAssetMaintenance
from .employee import Employee
from .invoice import Invoice
from .invoice_payment_ledger import InvoicePaymentLedger
from .order_item import OrderItem
from .ai_feedback import AIFeedback
from .shipping import ShippingCompany
from .shipping_payment import ShippingPayment
from .shipping_report import ShippingReport
from .ai_memory import AIMemory
from .message import Message
from .channel import ChannelMessage, ChannelRead
from .call import CallSession, CallSignal
from .system_analytics import SystemAnalytics
from .system_alert import SystemAlert
from .assistant_memory import AssistantMemory
from .role import Role, Permission
from .tenant import Tenant  # SaaS multi-tenant support
from .beauty_service import BeautyService
from .beauty_service_product import BeautyServiceProduct
from .beauty_appointment import BeautyAppointment
from .beauty_session_note import BeautySessionNote
from .ai_agent import (
    Agent,
    AgentWorkflow,
    AgentExecution,
    AgentExecutionLog,
    AgentComment,
)
from .telegram_inbox_message import TelegramInboxMessage
from .telegram_chat_profile import TelegramChatProfile
from .telegram_booking_session import TelegramBookingSession

# ======================================================
# Accounting Models (النماذج المحاسبية)
# ======================================================
from .account import Account, AccountType
from .journal_entry import JournalEntry
from .payment_order import PaymentOrder
from .payment_log import PaymentLog

# ======================================================
# Invoice Templates (قوالب الفواتير)
# ======================================================
from .invoice_template import InvoiceTemplate, TenantTemplatePurchase, TenantTemplateSettings

# ======================================================
# Landing Page CMS (Core DB)
# ======================================================
from .core.landing_content import (
    LandingCTA,
    LandingAuditLog,
    LandingFAQ,
    LandingFeature,
    LandingMedia,
    LandingModule,
    LandingPageSettings,
    LandingPricingPlan,
    LandingSEO,
    LandingSection,
    LandingTestimonial,
)
