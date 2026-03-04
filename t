You are a senior SaaS architect and Flask expert.

I have a Flask-based accounting SaaS project.
I want to temporarily disable real payment gateway integration and implement a manual ZainCash transfer system.

Goal:
Create a production-style Multi-Tenant SaaS architecture with:

1) Manual ZainCash Payment Flow
2) Admin Dashboard
3) Separate database per tenant (NO shared financial data between tenants)
4) Super Admin control panel

-----------------------------------
PART 1 — Disable Gateway
-----------------------------------

Remove any card input forms.
Replace checkout with:

"Pay via ZainCash transfer"

Display:
- ZainCash number
- Amount
- Order ID
- Instructions:
   Transfer and upload receipt screenshot

-----------------------------------
PART 2 — Manual Payment System
-----------------------------------

Create PaymentRequest model:

- id
- tenant_name
- owner_name
- phone
- email
- amount
- zaincash_reference (optional text field)
- receipt_image_path
- status (pending, approved, rejected)
- created_at

When user submits payment:
- Save as pending
- Store uploaded screenshot securely

-----------------------------------
PART 3 — Admin Dashboard (Super Admin)
-----------------------------------

Create SuperAdmin panel:

Login required.

Features:
- View all payment requests
- Approve / Reject
- On approval:
    - Create tenant
    - Generate separate SQLite DB file:
         /tenants/{tenant_slug}.db
    - Run automatic DB initialization (create tables)
    - Activate subscription
    - Set subscription_end_date = now + 30 days

-----------------------------------
PART 4 — Multi-Tenant Architecture
-----------------------------------

Each tenant must have:
- Separate database file
- Separate users
- Separate financial data
- No cross-access

Use dynamic DB binding:

On login:
- Detect tenant by subdomain or slug
- Connect to correct database

Example:
supermax.space/acme
supermax.space/finora

-----------------------------------
PART 5 — Tenant Model (Main DB)
-----------------------------------

Main database (core.db) stores:

Tenant:
- id
- name
- slug
- db_path
- subscription_end_date
- is_active
- created_at

SuperAdmin:
- id
- username
- password_hash

-----------------------------------
PART 6 — Security
-----------------------------------

- File upload validation
- Max image size limit
- Only image extensions allowed
- Hash tenant slug
- Prevent path traversal
- Protect admin routes

-----------------------------------
PART 7 — UI Pages Needed
-----------------------------------

1) zaincash_checkout.html
2) upload_receipt.html
3) admin_dashboard.html
4) tenant_list.html
5) payment_requests.html

-----------------------------------
PART 8 — Code Requirements
-----------------------------------

- Flask Blueprints
- SQLAlchemy
- SQLite
- Clean modular structure
- Production-style structure
- No shortcuts
- Proper error handling
- Comments explaining logic

-----------------------------------
IMPORTANT:
This must behave like a real SaaS architecture.
No simplified mock logic.
Each tenant must be fully isolated.
Write complete models, routes, and DB initialization logic.
