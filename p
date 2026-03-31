Fix my WhatsApp Cloud API sending code to stop using the default "hello_world" template and instead use my approved template "promo_offer".

Requirements:

1. Replace any usage of:
   "name": "hello_world"
with:
   "name": "promo_offer"

2. Ensure the message uses template format (not text).

3. Add required parameters for the template:
   {{1}} -> customer name
   {{2}} -> product name
   {{3}} -> price

4. Final request body must be:

{
  "messaging_product": "whatsapp",
  "to": customer_phone,
  "type": "template",
  "template": {
    "name": "promo_offer",
    "language": { "code": "ar" },
    "components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": customer_name},
          {"type": "text", "text": product_name},
          {"type": "text", "text": price}
        ]
      }
    ]
  }
}

5. Ensure:
- Access token is passed correctly
- Phone Number ID is used correctly in URL
- Handle API errors and print response

6. Add function:

send_whatsapp_template(phone, name, product, price)

7. Replace any old sending logic with this function

8. Make code clean and production-ready

9. Add console logs:
- success send
- error response

10. If code is using Flask or workflow system:
- update WhatsApp Send node to use template instead of text
- map variables correctly
