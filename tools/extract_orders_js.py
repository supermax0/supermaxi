import pathlib


def main() -> None:
    project_root = pathlib.Path(r"c:\Users\msi\Desktop\accounting_system")
    orders_html = project_root / "templates" / "orders.html"
    out_js = project_root / "__tmp_orders_js__.js"

    text = orders_html.read_text(encoding="utf-8", errors="ignore")

    # Extract the large JS block that starts after the ordersData JSON block.
    start_anchor = 'id="ordersData"'
    start = text.find(start_anchor)
    if start == -1:
        raise SystemExit(f"Anchor not found: {start_anchor}")

    script_open = "<script>"
    script_close = "</script>"
    idx = text.find(script_open, start)
    if idx == -1:
        raise SystemExit("No <script> found after ordersData")

    end = text.find(script_close, idx)
    if end == -1:
        raise SystemExit("No </script> found for extracted script")

    js = text[idx + len(script_open) : end]
    out_js.write_text(js, encoding="utf-8")

    print(f"Wrote: {out_js}")
    print(f"Chars: {len(js)}")
    print(f"Contains Jinja '{{{{' : {'{{' in js}")
    print(f"Contains Jinja '{{%': {'{%' in js}")


if __name__ == "__main__":
    main()

