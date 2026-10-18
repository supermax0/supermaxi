# Store API

واجهة المتجر الإلكتروني. الرمز `sk_` يقرأ ويعدّل ما يظهر للزبون: المنتجات، الأقسام، طلبات المتجر، زبائن تلك الطلبات، وإعدادات الواجهة والشحن والكوبون.

المخزون نفسه لا يُحذف. إخفاء منتج يبقيه في المخزون ويخرجه من المتجر فقط. طلبات نقطة البيع لا تظهر هنا.

## الربط

من **إعدادات المتجر → ربط API** انسخ:

| الحقل | القيمة |
|---|---|
| Store Name | اسم المتجر |
| Store URL | رابط المتجر `/shop/<tenant>/` |
| API Base URL | `https://<host>/api/v1/store` |
| API Token | `sk_<tenant>.<secret>` ويظهر مرة واحدة |

كل طلب يحتاج:

```http
Authorization: Bearer sk_<tenant>.<secret>
Content-Type: application/json
```

`GET /api/v1/store` يعيد حالة الاتصال والصلاحيات:

`catalog:read` `catalog:write` `orders:read` `orders:write` `customers:read` `customers:write` `settings:read` `settings:write`

## المنتجات

القائمة العامة ترجع الظاهر في المتجر فقط.

```http
GET /api/v1/store/products?q=&category=&sort=latest&availability=all&page=1&per_page=24
GET /api/v1/store/products?include_hidden=1
GET /api/v1/store/products/{id}
GET /api/v1/store/products/{id}?include_hidden=1
```

`sort`: `latest` أو `price_asc` أو `price_desc` أو `name_asc`.  
`availability`: `all` أو `in_stock` أو `out_stock`.

إنشاء منتج:

```http
POST /api/v1/store/products
```

```json
{
  "name": "مكيف جداري",
  "price": 180000,
  "category": "تكييف",
  "description": "وصف قصير",
  "sku": "AC-1",
  "image_url": "https://example.com/ac.jpg",
  "gallery": ["https://example.com/ac.jpg"],
  "old_price": 200000,
  "quantity": 4,
  "store_visible": true,
  "specs": [{"label": "الحجم", "value": "1 طن"}]
}
```

تعديل أي حقل من حقول الإنشاء، إضافة إلى `brand` و `featured` و `active`:

```http
PATCH /api/v1/store/products/{id}
```

إخفاء من المتجر (المنتج يبقى في المخزون):

```http
DELETE /api/v1/store/products/{id}
```

إظهار أو إخفاء دفعة، بحد 100 معرف:

```http
POST /api/v1/store/products/bulk
```

```json
{"ids": [12, 15], "store_visible": false}
```

## الأقسام

```http
GET /api/v1/store/categories
POST /api/v1/store/categories/rename
```

```json
{"from": "سبالت", "to": "تكييف"}
```

## طلبات المتجر

فقط الفواتير التي بدأت ملاحظتها بـ `طلب من متجر المنتجات`.

```http
GET /api/v1/store/orders?status=&page=1&per_page=24
GET /api/v1/store/orders/{id}
PATCH /api/v1/store/orders/{id}
```

```json
{"status": "قيد التجهيز", "payment_status": "مسدد"}
```

حالات الطلب: `تم الطلب` `قيد التجهيز` `قيد الشحن` `تم التوصيل` `مكتمل` `ملغي`.  
حالات الدفع: `غير مسدد` `جزئي` `مسدد` `مرتجع`.

## زبائن المتجر

زبائن لديهم طلب من المتجر، وليس كل زبائن النظام.

```http
GET /api/v1/store/customers?q=&page=1&per_page=24
PATCH /api/v1/store/customers/{id}
```

```json
{"name": "هدى", "phone": "07804445566", "city": "النجف", "address": "حي السعد", "notes": ""}
```

تغيير الاسم ينعكس على اسم الزبون في طلبات المتجر.

## إعدادات الواجهة

```http
GET /api/v1/store/settings
PATCH /api/v1/store/settings
```

الحقول المقبولة في التعديل:

- `store_name` `logo_url` `whatsapp`
- `primary_color` `shipping_color` `card_style` `theme_preset` `theme_mode`
- `hero_title` `hero_subtitle` `hero_mode` `hero_slides`
- `product_sections`
- `shipping_default_fee` `shipping_by_city`
- `coupon_code` `coupon_type` (`percent` أو `fixed`) `coupon_value`
- `ai_assistant_enabled` `ai_assistant_name` `ai_assistant_greeting`

مثال قسم في الصفحة:

```json
{
  "product_sections": [
    {
      "id": "offers",
      "title": "العروض",
      "enabled": true,
      "product_mode": "discount",
      "limit": 8
    }
  ]
}
```

`product_mode`: `all` أو `discount` أو `new` أو `category` أو `manual`.  
`card_style`: `modern` `compact` `showcase` `minimal` `bordered` `overlay`.

## الأخطاء

الرد عند الفشل:

```json
{"ok": false, "error": "النص", "code": "token_invalid"}
```

| الحالة | المعنى |
|---|---|
| 401 | الرمز ناقص أو ملغى |
| 404 | المنتج أو الطلب أو الزبون غير موجود في المتجر |
| 429 | طلبات أكثر من الحد |
