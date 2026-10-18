/** Supplier data is confined to the E2E stub; production always uses FINORA. */
export function createSupplierFixture() {
  const rows = [
    [3, "شركة الأمل", "07701234567", "بغداد - الكرادة", 45000000, 39800000],
    [4, "مؤسسة النور", "07801234567", "مستلزمات منزلية", 18500000, 18500000],
    [5, "شركة بغداد", "07709876543", "بغداد - المنصور", 12000000, 10250000],
    [6, "مكتب الخليج", "07805555555", "البصرة", 9800000, 9800000],
    [7, "شركة الريان", "07716667777", "أربيل", 25400000, 21800000],
    [8, "الشروق للتجارة", "07803334444", "بغداد", 7200000, 7200000],
    [9, "مؤسسة الثقة", "07777778888", "النجف", 3450000, 4400000],
    [10, "العالمي للتقنية", "07809999988", "بغداد", 16700000, 19200000],
  ].map(([id, name, phone, address, debt, paid], index) => ({
    id: Number(id),
    name: String(name),
    phone: String(phone),
    phone2: "",
    address: String(address),
    opening_balance: 0,
    total_debt: Number(debt),
    total_paid: Number(paid),
    remaining: Number(debt) - Number(paid),
    total_purchases: Number(debt),
    purchase_count: index === 0 ? 12 : 2,
    payment_count: index === 0 ? 18 : 1,
    last_transaction: `2026-10-${String(9 - index).padStart(2, "0")}`,
    created_at: "2026-09-01T10:00:00",
    member_count: 1,
  }));
  const payments = new Map<
    number,
    Array<{
      id: number;
      date: string;
      amount: number;
      note: string;
      document_number: string;
      payment_method: string;
      invoice_labels: string[];
    }>
  >();
  payments.set(3, [
    {
      id: 1,
      date: "2026-10-09T12:00:00",
      amount: 5200000,
      note: "دفعة على الحساب",
      document_number: "PAY-001",
      payment_method: "cash",
      invoice_labels: ["P-0048"],
    },
  ]);
  const saleProducts = [
    {
      id: 201,
      name: "شاشة LG 50",
      sku: "TV-LG-50",
      barcode: "6290000000011",
      sale_price: 325000,
      quantity: 8,
      has_colors: false,
      colors: [],
    },
    {
      id: 202,
      name: "سماعة ملونة",
      sku: "SP-COLOR",
      barcode: "6290000000099",
      sale_price: 50000,
      quantity: 3,
      has_colors: true,
      colors: [
        { name: "أسود", qty: 2, sale_price: 50000 },
        { name: "أبيض", qty: 1, sale_price: 55000 },
      ],
    },
  ];
  const sales = new Map<
    number,
    Array<{ id: number; invoice_no: string; date: string; grand_total: number; products_label: string }>
  >();
  return {
    snapshotData: () => ({ rows: structuredClone(rows), products: structuredClone(saleProducts) }),
    handle(path: string, method: string, url: URL, body: Record<string, unknown>) {
      if (path === "/suppliers/api/sale-products") {
        const q = (url.searchParams.get("q") ?? "").trim();
        return {
          status: 200,
          data: q ? saleProducts.filter((p) => `${p.name} ${p.sku} ${p.barcode}`.includes(q)) : [],
        };
      }
      if (path === "/suppliers/api/page") {
        const search = (url.searchParams.get("search") ?? "").toLowerCase();
        const minimum = Number(url.searchParams.get("min_balance") ?? 0);
        const matches = rows.filter(
          (s) =>
            `${s.name} ${s.phone} ${s.address}`.toLowerCase().includes(search) &&
            Math.abs(s.remaining) >= minimum,
        );
        const counts = {
          all: matches.length,
          debt: matches.filter((s) => s.remaining > 0).length,
          credit: matches.filter((s) => s.remaining < 0).length,
          settled: matches.filter((s) => s.remaining === 0).length,
        };
        const tab = url.searchParams.get("tab") ?? "all";
        const filtered = matches.filter(
          (s) =>
            tab === "all" ||
            (tab === "debt" && s.remaining > 0) ||
            (tab === "credit" && s.remaining < 0) ||
            (tab === "settled" && s.remaining === 0),
        );
        const pageSize = Number(url.searchParams.get("page_size") ?? 25);
        const page = Number(url.searchParams.get("page") ?? 1);
        return {
          status: 200,
          data: {
            success: true,
            rows: filtered.slice((page - 1) * pageSize, page * pageSize),
            page,
            page_size: pageSize,
            total: filtered.length,
            total_pages: Math.max(1, Math.ceil(filtered.length / pageSize)),
            counts,
            summary: {
              count: rows.length,
              payable: rows.reduce((n, s) => n + Math.max(s.remaining, 0), 0),
              credit: rows.reduce((n, s) => n + Math.max(-s.remaining, 0), 0),
              purchases: rows.reduce((n, s) => n + s.total_purchases, 0),
            },
          },
        };
      }
      if (path === "/suppliers/api/create" && method === "POST") {
        const id = Math.max(...rows.map((s) => s.id)) + 1;
        const opening = Number(body.opening_balance ?? 0);
        rows.push({
          id,
          name: String(body.name),
          phone: String(body.phone ?? ""),
          phone2: String(body.phone2 ?? ""),
          address: String(body.address ?? ""),
          opening_balance: opening,
          total_debt: opening,
          total_paid: 0,
          remaining: opening,
          total_purchases: 0,
          purchase_count: 0,
          payment_count: 0,
          last_transaction: "",
          created_at: "2026-10-09T12:00:00",
          member_count: 1,
        });
        return { status: 200, data: { success: true, id, message: "تمت إضافة المورد بنجاح" } };
      }
      const match = /^\/suppliers\/api\/(\d+)(?:\/(update|pay|sale))?$/.exec(path);
      if (!match) return null;
      const s = rows.find((s) => s.id === Number(match[1]));
      if (!s) return { status: 404, data: { error: "المورد غير موجود" } };
      if (match[2] === "sale" && method === "POST") {
        const items = body.items as Array<{
          product_id: number;
          qty: number;
          price: number;
          variant_color?: string;
        }>;
        const total = items.reduce((n, item) => n + item.qty * item.price, 0);
        const previous = sales.get(s.id) ?? [];
        const id = previous.length + 1;
        const invoice_no = `SS-20261009-${String(id).padStart(4, "0")}`;
        for (const item of items) {
          const product = saleProducts.find((p) => p.id === item.product_id);
          if (!product) throw new Error("Unknown supplier sale fixture product");
          product.quantity -= item.qty;
          const color = product.colors.find((c) => c.name === item.variant_color);
          if (color) color.qty -= item.qty;
        }
        s.total_paid += total;
        s.remaining -= total;
        sales.set(s.id, [
          {
            id,
            invoice_no,
            date: "2026-10-09",
            grand_total: total,
            products_label: items
              .map((i) => saleProducts.find((p) => p.id === i.product_id)?.name ?? "")
              .join("، "),
          },
          ...previous,
        ]);
        return {
          status: 200,
          data: {
            success: true,
            message: "تم تسجيل البيع",
            sale_id: id,
            invoice_no,
            grand_total: total,
            remaining: s.remaining,
            supplier_receivable: Math.max(-s.remaining, 0),
          },
        };
      }
      if (match[2] === "update" && method === "POST") {
        Object.assign(s, {
          name: String(body.name),
          phone: String(body.phone),
          phone2: String(body.phone2),
          address: String(body.address),
        });
        return { status: 200, data: { success: true, id: s.id, message: "تم تحديث بيانات المورد" } };
      }
      if (match[2] === "pay" && method === "POST") {
        const amount = Number(body.amount);
        if (amount <= 0 || amount > s.remaining) return { status: 400, data: { error: "المبلغ غير صحيح" } };
        s.total_paid += amount;
        s.remaining -= amount;
        s.payment_count += 1;
        const previous = payments.get(s.id) ?? [];
        payments.set(s.id, [
          {
            id: previous.length + 1,
            date: String(body.payment_date),
            amount,
            note: String(body.note ?? ""),
            document_number: String(body.document_number ?? ""),
            payment_method: "cash",
            invoice_labels: [],
          },
          ...previous,
        ]);
        return { status: 200, data: { success: true, id: s.id, message: "تم تسجيل الدفعة" } };
      }
      return {
        status: 200,
        data: {
          success: true,
          supplier: s,
          purchases:
            s.total_purchases > 0
              ? [
                  {
                    id: 48,
                    invoice_no: "P-0048",
                    date: "2026-10-09",
                    status: "confirmed",
                    products_label: "شاشات وأجهزة إلكترونية",
                    grand_total: s.total_purchases,
                    paid_total: Math.min(s.total_paid, s.total_purchases),
                    remaining_total: Math.max(s.remaining, 0),
                  },
                ]
              : [],
          payments: payments.get(s.id) ?? [],
          sales: sales.get(s.id) ?? [],
          treasury_accounts: [{ id: 1, name: "الصندوق الرئيسي", is_default: true }],
        },
      };
    },
  };
}
