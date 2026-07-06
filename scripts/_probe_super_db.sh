#!/bin/bash
DB=/var/www/finora/supermaxi/tenants/super.db
echo "=== 83000 txs ==="
sqlite3 "$DB" "SELECT id, type, amount, note, created_at FROM account_transaction WHERE amount=83000;"
echo "=== last 25 txs ==="
sqlite3 "$DB" "SELECT id, type, amount, note, created_at FROM account_transaction ORDER BY id DESC LIMIT 25;"
echo "=== sum deposits/withdraws ==="
sqlite3 "$DB" "SELECT type, SUM(amount) FROM account_transaction GROUP BY type;"
echo "=== 300000 withdraws ==="
sqlite3 "$DB" "SELECT id, type, amount, note, created_at FROM account_transaction WHERE amount=300000 OR amount=150000 OR amount=100000 ORDER BY created_at DESC LIMIT 15;"
