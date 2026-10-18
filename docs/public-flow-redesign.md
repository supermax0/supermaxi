# Public account and subscription pages

The landing page identity now continues through login, signup, monthly pricing, WhatsApp activation, payment summary, ZainCash checkout, payment receipt/failure, password change, upgrade, terms and privacy.

- `templates/public_flow/base.html` supplies the shared RTL shell, local Arabic fonts, escaped flash messages, footer and styles. Business dashboard layouts remain separate.
- `static/css/public-flow.css` layers the cream/burgundy design over existing payment form components. Desktop login and registration use the same real inventory screenshot documented in `static/images/landing/README.md`.
- Login preserves fixed company links, session-switch confirmation, password visibility and the existing `finora_login_remember_v1` storage format. Only company identifier and username are remembered.
- Signup renders the actual `plans_dict` instead of hardcoded cards and limits. Billing prices remain server supplied. Account information comes before WhatsApp consent; the existing phone, password, discovery-source and activation validation remains in place. Unverified savings claims were removed. Free plans show their trial duration.
- Checkout form destinations, fields, amounts, uploads and review states are unchanged. There are no backend authentication, provisioning or payment modifications. Legal article text is unchanged.

Verification: `py -3.11 -m pytest tests/test_public_flow_templates.py tests/test_landing_product.py -q`. The existing credential tests also exercise forced password change and login against temporary databases.

Read-only visual preview: `py -3.11 output/public-flow-redesign/preview.py` serves port 5017 using illustrative fixture plans and account data; it cannot create accounts or accept payments. `node output/public-flow-redesign/check.mjs` verifies 12 pages at 1440, 768, 390 and 360 pixels, plus form interactions. Screenshots and browser results are in `output/public-flow-redesign/`. This preview is local and is not a production deployment.
