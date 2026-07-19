import sqlite3
import sys


def main() -> int:
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--repair"):
        print("usage: verify_ai_calling_schema.py TENANT_DB [--repair]")
        return 2

    connection = sqlite3.connect(sys.argv[1])
    try:
        repair = len(sys.argv) == 3
        channel_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(ai_sales_channel_account)"
            )
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required_columns = {
            "calling_status",
            "calling_settings_json",
            "calling_last_checked_at",
        }
        missing_columns = sorted(required_columns - channel_columns)
        missing_tables = [] if "ai_sales_call" in tables else ["ai_sales_call"]

        if repair and missing_columns:
            definitions = {
                "calling_status": "VARCHAR(30) NOT NULL DEFAULT 'unknown'",
                "calling_settings_json": "TEXT",
                "calling_last_checked_at": "DATETIME",
            }
            for column in missing_columns:
                connection.execute(
                    "ALTER TABLE ai_sales_channel_account "
                    f"ADD COLUMN {column} {definitions[column]}"
                )
            connection.commit()
            channel_columns.update(missing_columns)
            missing_columns = []
            print("repair=applied")

        print(f"missing_columns={missing_columns}")
        print(f"missing_tables={missing_tables}")
        if "ai_sales_call" in tables:
            call_count = connection.execute(
                "SELECT COUNT(*) FROM ai_sales_call"
            ).fetchone()[0]
            print(f"call_count={call_count}")
        selected_columns = ["id", "channel_type", "phone_number_id", "connection_status"]
        selected_columns.extend(
            column
            for column in ("calling_status", "last_error")
            if column in channel_columns
        )
        channel = connection.execute(
            "SELECT " + ", ".join(selected_columns)
            + " FROM ai_sales_channel_account WHERE id = 1"
        ).fetchone()
        print(f"whatsapp_channel={channel}")
        return 1 if missing_columns or missing_tables else 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
