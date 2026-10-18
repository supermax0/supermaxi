# Clinics Authorization Route Inventory

Generated from route decorators. This is an inventory, NOT a completed security audit. Public routes use a separate trust model. Dynamic dispatch and service-level checks need manual review.

| Source | Handler | Route | Methods | Declared permission | Review status |
|---|---|---|---|---|---|
| modules/clinics/public_routes.py:63 | booking_page | `/<tenant_slug>` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:78 | api_info | `/<tenant_slug>/api/info` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:78 | api_info | `/<tenant_slug>` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:86 | api_public_doctors | `/<tenant_slug>/doctors` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:98 | api_public_specialties | `/<tenant_slug>/specialties` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:106 | api_public_services | `/<tenant_slug>/services` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:117 | api_slots | `/<tenant_slug>/api/slots` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:117 | api_slots | `/<tenant_slug>/available-slots` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:130 | api_book | `/<tenant_slug>/api/book` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:130 | api_book | `/<tenant_slug>/bookings` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:147 | api_otp | `/<tenant_slug>/api/otp` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:161 | api_first_available | `/<tenant_slug>/api/first-available` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:161 | api_first_available | `/<tenant_slug>/first-available` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:172 | api_public_chat | `/<tenant_slug>/api/chat` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:172 | api_public_chat | `/<tenant_slug>/conversations` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:190 | api_public_chat_messages | `/<tenant_slug>/api/chat/<token>/messages` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:190 | api_public_chat_messages | `/<tenant_slug>/conversations/<token>/messages` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:199 | api_public_chat_send | `/<tenant_slug>/api/chat/<token>/messages` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:199 | api_public_chat_send | `/<tenant_slug>/conversations/<token>/messages` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:209 | manage_page | `/<tenant_slug>/manage/<token>` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:219 | api_manage | `/<tenant_slug>/api/manage/<token>` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:227 | api_manage_reschedule | `/<tenant_slug>/api/manage/<token>/reschedule` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/public_routes.py:237 | api_manage_cancel | `/<tenant_slug>/api/manage/<token>/cancel` | POST | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/routes.py:89 | dashboard_page | `/` | GET | 'clinics_dashboard' | Pending full review |
| modules/clinics/routes.py:96 | doctor_visit_page | `/doctor/<int:visit_id>` | GET | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:107 | doctor_profile_page | `/doctors/<int:doctor_id>` | GET | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:118 | patient_detail_page | `/patients/<int:patient_id>` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:129 | inventory_item_page | `/inventory/items/<int:item_id>` | GET | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:138 | inventory_subpage | `/inventory/<view>` | GET | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:149 | purchases_new_page | `/purchases/new` | GET | 'purchases.create' | Pending full review |
| modules/clinics/routes.py:160 | purchases_reports_page | `/purchases/reports` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:171 | purchases_edit_page | `/purchases/<int:purchase_id>/edit` | GET | 'purchases.edit' | Pending full review |
| modules/clinics/routes.py:183 | purchases_detail_page | `/purchases/<int:purchase_id>` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:194 | calendar_redirect | `/calendar` | GET | 'clinics_appointments' | Pending full review |
| modules/clinics/routes.py:200 | workspace_page | `/<page>` | GET | No require_clinics decorator - inspect | Pending full review |
| modules/clinics/routes.py:220 | api_bootstrap | `/api/bootstrap` | GET | authenticated clinics user | Pending full review |
| modules/clinics/routes.py:239 | api_dashboard | `/api/dashboard` | GET | 'clinics_dashboard' | Pending full review |
| modules/clinics/routes.py:264 | api_dashboard_pulse | `/api/dashboard/pulse` | GET | 'clinics_dashboard' | Pending full review |
| modules/clinics/routes.py:286 | api_check_phone | `/api/patients/check-phone` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:297 | api_check_similar | `/api/patients/check-similar` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:310 | api_patients_registry | `/api/patients/registry` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:338 | api_patients_export | `/api/patients/export` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:431 | api_queue_reorder | `/api/queue/reorder` | POST | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:446 | api_queue_recall | `/api/queue/recall` | POST | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:461 | api_queue_enqueue | `/api/queue/enqueue` | POST | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:473 | api_appointment_priority | `/api/appointments/<int:appointment_id>/priority` | POST | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:491 | api_appointment_emergency | `/api/appointments/<int:appointment_id>/emergency` | POST | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:508 | api_search | `/api/search` | GET | authenticated clinics user | Pending full review |
| modules/clinics/routes.py:522 | api_settings | `/api/settings` | GET, PUT, POST | 'clinics_settings' | Pending full review |
| modules/clinics/routes.py:538 | api_patients | `/api/patients` | GET, POST | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:553 | api_patient_detail | `/api/patients/<int:patient_id>` | GET, PUT, PATCH | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:571 | api_doctors_center | `/api/doctors/center` | GET | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:582 | api_doctor_employee_candidates | `/api/doctors/employees` | GET | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:593 | api_doctor_workspace | `/api/doctors/<int:doctor_id>/workspace` | GET | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:612 | api_doctor_employee_link | `/api/doctors/<int:doctor_id>/employee-link` | PATCH | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:627 | api_doctors | `/api/doctors` | GET, POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:642 | api_doctor_update | `/api/doctors/<int:doctor_id>` | PUT, PATCH | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:655 | api_specialties | `/api/specialties` | GET, POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:669 | api_specialty_detail | `/api/specialties/<int:specialty_id>` | GET, PUT, PATCH | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:687 | api_specialty_templates | `/api/specialties/<int:specialty_id>/templates` | GET, POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:703 | api_publish_visit_template | `/api/visit-templates/<int:template_id>/publish` | POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:715 | api_visit_template | `/api/visit-templates/<int:template_id>` | GET, PUT | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:729 | api_archive_visit_template | `/api/visit-templates/<int:template_id>/archive` | POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:741 | api_services | `/api/services` | GET, POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:758 | api_service_update | `/api/services/<int:service_id>` | PUT, PATCH | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:771 | api_rooms | `/api/rooms` | GET, POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:789 | api_reception | `/api/reception` | GET | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:813 | api_appointment_slots | `/api/appointments/slots` | GET | 'clinics_appointments' | Pending full review |
| modules/clinics/routes.py:838 | api_appointment_detail | `/api/appointments/<int:appointment_id>` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:847 | api_appointments_board | `/api/appointments/board` | GET | 'clinics_appointments' | Pending full review |
| modules/clinics/routes.py:877 | api_appointments | `/api/appointments` | GET, POST | 'clinics_appointments' | Pending full review |
| modules/clinics/routes.py:903 | api_patch_appointment | `/api/appointments/<int:appointment_id>` | PATCH | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:919 | api_appointment_status | `/api/appointments/<int:appointment_id>/status` | POST | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:940 | api_visits | `/api/visits` | GET, POST | 'clinics_visits' | Pending full review |
| modules/clinics/routes.py:965 | api_visits_registry | `/api/visits/registry` | GET | 'clinics_visits' | Pending full review |
| modules/clinics/routes.py:994 | api_visit_get | `/api/visits/<int:visit_id>` | GET | 'clinics_visits' | Pending full review |
| modules/clinics/routes.py:1003 | api_visit_update | `/api/visits/<int:visit_id>` | PUT, PATCH | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1016 | api_visit_vitals | `/api/visits/<int:visit_id>/vitals` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1029 | api_visit_specialty_values | `/api/visits/<int:visit_id>/specialty-values` | PUT | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1041 | api_specialty_attachment | `/api/visits/<int:visit_id>/specialty-attachment` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1067 | api_visit_diagnosis | `/api/visits/<int:visit_id>/diagnoses` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1080 | api_visit_rx | `/api/visits/<int:visit_id>/prescription` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1093 | api_visit_complete | `/api/visits/<int:visit_id>/complete` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1108 | api_visit_treatment_bill | `/api/visits/<int:visit_id>/treatment-bill` | GET | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1119 | api_visit_treatment_bill_add | `/api/visits/<int:visit_id>/treatment-bill/lines` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1134 | api_visit_treatment_bill_delete | `/api/visits/<int:visit_id>/treatment-bill/lines/<int:line_id>` | DELETE | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1150 | api_invoices | `/api/invoices` | GET | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:1161 | api_invoice_pay | `/api/invoices/<int:invoice_id>/pay` | POST | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:1178 | api_patient_statement | `/api/patients/<int:patient_id>/statement` | GET | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:1192 | api_schedules | `/api/schedules` | GET, POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:1210 | api_schedule_delete | `/api/schedules/<int:schedule_id>` | DELETE | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:1223 | api_time_off | `/api/time-off` | GET, POST | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:1239 | api_room_update | `/api/rooms/<int:room_id>` | PUT, PATCH | 'clinics_admin' | Pending full review |
| modules/clinics/routes.py:1255 | api_inventory | `/api/inventory` | GET, POST | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1281 | api_inventory_item | `/api/inventory/<int:item_id>` | GET, PUT, PATCH | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1295 | api_inventory_stock_in | `/api/inventory/<int:item_id>/stock-in` | POST | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1308 | api_inventory_stock_out | `/api/inventory/<int:item_id>/stock-out` | POST | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1320 | api_inventory_batches | `/api/inventory/batches` | GET | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1331 | api_inventory_movements | `/api/inventory/movements` | GET | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1343 | api_inventory_alerts | `/api/inventory/alerts` | GET | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1357 | api_procedures | `/api/procedures` | GET, POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1375 | api_visit_procedures | `/api/visits/<int:visit_id>/procedures` | GET, POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1395 | api_lab_tests | `/api/lab-tests` | GET, POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1410 | api_lab_orders | `/api/lab-orders` | GET, POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1435 | api_lab_result | `/api/lab-order-items/<int:item_id>/result` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1450 | api_radiology_orders | `/api/radiology-orders` | GET, POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1475 | api_radiology_result | `/api/radiology-orders/<int:order_id>/result` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1493 | api_settlements | `/api/settlements` | GET, POST | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:1519 | api_reports_summary | `/api/reports/summary` | GET | 'clinics_reports', 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:1533 | api_reports_hub | `/api/reports/hub` | GET | 'clinics_reports', 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:1545 | api_reports_export | `/api/reports/export` | GET | 'clinics_reports', 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:1607 | api_public_queue | `/api/public-queue` | GET | 'clinics_reception' | Pending full review |
| modules/clinics/routes.py:1623 | api_comms_dashboard | `/api/communications` | GET | 'clinics_communications_view' | Pending full review |
| modules/clinics/routes.py:1636 | api_conversations | `/api/communications/conversations` | GET, POST | 'clinics_communications_view' | Pending full review |
| modules/clinics/routes.py:1652 | api_conversation | `/api/communications/conversations/<int:conversation_id>` | GET, PUT | 'clinics_communications_view' | Pending full review |
| modules/clinics/routes.py:1671 | api_conversation_message | `/api/communications/conversations/<int:conversation_id>/messages` | POST | 'clinics_communications_reply' | Pending full review |
| modules/clinics/routes.py:1683 | api_conversation_patient | `/api/communications/conversations/<int:conversation_id>/patient` | POST | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:1695 | api_conversation_followup | `/api/communications/conversations/<int:conversation_id>/followups` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1707 | api_conversation_task | `/api/communications/conversations/<int:conversation_id>/tasks` | POST | 'clinics_communications_reply' | Pending full review |
| modules/clinics/routes.py:1719 | api_communication_templates | `/api/communications/templates` | GET, POST | 'clinics_communications_view' | Pending full review |
| modules/clinics/routes.py:1736 | api_booking_requests | `/api/communications/booking-requests` | GET | 'clinics_booking_requests_view' | Pending full review |
| modules/clinics/routes.py:1746 | api_booking_request_decision | `/api/communications/booking-requests/<int:booking_request_id>/<action>` | POST | 'clinics_booking_requests_approve' | Pending full review |
| modules/clinics/routes.py:1758 | api_reminder_center | `/api/communications/reminders` | GET | 'clinics_reminders_view' | Pending full review |
| modules/clinics/routes.py:1768 | api_reminder_rule_save | `/api/communications/reminder-rules` | POST | 'clinics_reminders_manage' | Pending full review |
| modules/clinics/routes.py:1780 | api_communication_settings | `/api/communications/settings` | POST | 'clinics_booking_settings_manage' | Pending full review |
| modules/clinics/routes.py:1804 | api_messages | `/api/messages` | GET | 'clinics_settings' | Pending full review |
| modules/clinics/routes.py:1815 | api_process_reminders | `/api/reminders/process` | POST | 'clinics_settings' | Pending full review |
| modules/clinics/routes.py:1829 | api_followups | `/api/followups` | GET, POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1859 | api_followup_update | `/api/followups/<int:followup_id>` | PUT, PATCH | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:1875 | api_suppliers | `/api/suppliers` | GET, POST | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1890 | api_supplier_statement | `/api/suppliers/<int:supplier_id>/statement` | GET | 'clinics_inventory' | Pending full review |
| modules/clinics/routes.py:1901 | api_purchases_meta | `/api/purchases/meta` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:1909 | api_purchase_reports_item | `/api/purchases/reports/by-item` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:1920 | api_purchase_reports_category | `/api/purchases/reports/by-category` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:1931 | api_purchase_reports_pending | `/api/purchases/reports/pending-receipt` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:1942 | api_purchase_reports_returns | `/api/purchases/reports/returns` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:1953 | api_purchase_reports_price_changes | `/api/purchases/reports/price-changes` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:1964 | api_purchases_kpis | `/api/purchases/kpis` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:1975 | api_purchases_check_duplicate | `/api/purchases/check-duplicate` | GET | 'purchases.create' | Pending full review |
| modules/clinics/routes.py:1993 | api_purchases | `/api/purchases` | GET, POST | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2013 | api_purchase_reports_unpaid | `/api/purchases/reports/unpaid` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:2024 | api_purchase_reports_supplier | `/api/purchases/reports/by-supplier` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:2035 | api_purchase_price_history | `/api/purchases/price-history` | GET | 'purchases.cost.view' | Pending full review |
| modules/clinics/routes.py:2047 | api_purchase_price_check | `/api/purchases/price-check` | POST | 'purchases.create' | Pending full review |
| modules/clinics/routes.py:2059 | api_purchase_reorder | `/api/purchases/reorder-suggestions` | GET | 'purchase_request.create' | Pending full review |
| modules/clinics/routes.py:2070 | api_purchase_reports | `/api/purchases/reports/summary` | GET | 'purchases.export' | Pending full review |
| modules/clinics/routes.py:2081 | api_purchase_update | `/api/purchases/<int:purchase_id>` | PUT | 'purchases.edit' | Pending full review |
| modules/clinics/routes.py:2094 | api_purchase_copy | `/api/purchases/<int:purchase_id>/copy` | POST | 'purchases.create' | Pending full review |
| modules/clinics/routes.py:2107 | api_purchase_approve | `/api/purchases/<int:purchase_id>/approve` | POST | 'purchases.approve' | Pending full review |
| modules/clinics/routes.py:2120 | api_purchase_validate_receive | `/api/purchases/<int:purchase_id>/validate-receive` | POST | 'purchases.receive' | Pending full review |
| modules/clinics/routes.py:2139 | api_purchase_detail | `/api/purchases/<int:purchase_id>` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2150 | api_purchase_payment | `/api/purchases/<int:purchase_id>/payments` | POST | 'purchases.payment.create' | Pending full review |
| modules/clinics/routes.py:2165 | api_purchase_cancel | `/api/purchases/<int:purchase_id>/cancel` | POST | 'purchases.cancel' | Pending full review |
| modules/clinics/routes.py:2178 | api_purchase_receive | `/api/purchases/<int:purchase_id>/receive` | POST | 'purchases.receive' | Pending full review |
| modules/clinics/routes.py:2193 | api_purchase_requests | `/api/purchase-requests` | GET | 'purchase_request.create' | Pending full review |
| modules/clinics/routes.py:2204 | api_purchase_requests_create | `/api/purchase-requests` | POST | 'purchase_request.create' | Pending full review |
| modules/clinics/routes.py:2217 | api_purchase_request_status | `/api/purchase-requests/<int:request_id>/status` | POST | 'purchase_request.approve' | Pending full review |
| modules/clinics/routes.py:2233 | api_purchase_request_convert | `/api/purchase-requests/<int:request_id>/convert` | POST | 'purchases.create' | Pending full review |
| modules/clinics/routes.py:2248 | api_purchase_return | `/api/purchases/<int:purchase_id>/returns` | POST | 'purchases.return' | Pending full review |
| modules/clinics/routes.py:2263 | api_purchase_attachments | `/api/purchases/<int:purchase_id>/attachments` | GET, POST | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2290 | api_purchase_attachment_download | `/api/purchases/attachments/<int:attachment_id>/download` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2304 | purchase_print_page | `/purchases/<int:purchase_id>/print` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2313 | purchase_receipt_print_page | `/purchases/<int:purchase_id>/receipts/<int:receipt_id>/print` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2322 | purchase_payment_print_page | `/purchases/<int:purchase_id>/payments/<int:payment_id>/print` | GET | 'purchases.payment.view' | Pending full review |
| modules/clinics/routes.py:2331 | purchase_return_print_page | `/purchases/<int:purchase_id>/returns/<int:return_id>/print` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2340 | supplier_statement_print_page | `/suppliers/<int:supplier_id>/statement/print` | GET | 'purchases.view' | Pending full review |
| modules/clinics/routes.py:2351 | api_calendar | `/api/calendar` | GET | 'clinics_appointments' | Pending full review |
| modules/clinics/routes.py:2373 | api_reschedule | `/api/appointments/<int:appointment_id>/reschedule` | POST | 'clinics_appointments' | Pending full review |
| modules/clinics/routes.py:2389 | api_expenses | `/api/expenses` | GET, POST | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:2408 | api_refund | `/api/invoices/<int:invoice_id>/refund` | POST | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:2423 | api_cash_sessions | `/api/cash-sessions` | GET, POST | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:2440 | api_cash_close | `/api/cash-sessions/<int:session_id>/close` | POST | 'clinics_billing' | Pending full review |
| modules/clinics/routes.py:2458 | api_attachments | `/api/attachments` | GET, POST | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:2485 | api_attachment_download | `/api/attachments/<int:attachment_id>/download` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:2499 | api_attachment_preview | `/api/attachments/<int:attachment_id>/preview` | GET | 'clinics_patients' | Pending full review |
| modules/clinics/routes.py:2511 | api_followup_contact | `/api/followups/<int:followup_id>/contact` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2523 | api_radiology_workflow | `/api/radiology-orders/<int:order_id>/workflow` | PATCH | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2537 | api_lab_workflow | `/api/lab-orders/<int:order_id>/workflow` | PATCH | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2551 | api_procedure_update | `/api/procedures/<int:procedure_id>` | PUT | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2563 | api_procedure_execution_create | `/api/procedure-executions` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2575 | api_procedure_execution_update | `/api/procedure-executions/<int:execution_id>` | PATCH | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2589 | api_clinical_recent_patients | `/api/clinical/recent-patients` | GET | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2599 | api_clinical_record | `/api/clinical/patients/<int:patient_id>` | GET | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2611 | api_clinical_print_audit | `/api/clinical/patients/<int:patient_id>/print-audit` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2623 | api_consents | `/api/consents` | GET, POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2638 | api_consent_sign | `/api/consents/<int:consent_id>/sign` | POST | 'clinics_clinical' | Pending full review |
| modules/clinics/routes.py:2653 | api_specialty_seed | `/api/specialty/seed` | POST | 'clinics_settings' | Pending full review |
| modules/clinics/routes.py:2667 | api_booking_qr | `/api/booking-qr` | GET | 'clinics_settings' | Pending full review |
| modules/clinics/routes.py:2689 | api_jobs_run | `/api/jobs/run` | POST | 'clinics_settings' | Pending full review |
