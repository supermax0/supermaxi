# Finora AI tools

Tools are grounded on catalog/cart/rewards/orders (`services/ai_tools.py`).

Notable: `add_item_to_cart` requires explicit `confirm-action`. Under `TESTING` the assistant uses a rule-based fallback (no OpenAI call).
