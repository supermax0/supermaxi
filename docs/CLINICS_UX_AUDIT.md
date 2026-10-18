# FINORA Clinics UX Audit

**Date:** 2026-09-04  
**Base schema:** `clinics-v23-pediatric-clinical-tools`  
**Baseline tests:** 168 passed

## Current routes

Dashboard, reception, appointments, queue, display, patients, patient_detail, visits, doctor, clinical, labs, radiology, followups, procedures, billing, expenses, cash, settlements, inventory (+movements/batches/expiry), suppliers, purchases, doctors, specialties, schedules, services, rooms, communications, reports, settings, attachments.

## Current sidebar items

~28 visible links across 6 flat groups (daily ops, patients, clinical, finance, inventory, admin). Inventory movements/batches and many admin items compete with daily work.

## Duplicate navigation

- Inventory movements/batches also reachable from inventory UI.
- Attachments vs patient profile attachments.
- Clinical registry vs visits vs doctor workspace overlap for doctors.
- Topbar always pushes Reception + Display even for doctor-only staff.

## Pages that should become subpages

- Inventory movements / batches / expiry → Inventory tabs (keep URLs).
- Expenses / cash / settlements → Finance cluster (keep URLs, sidebar under expandable مالية).
- Suppliers → under Inventory/Purchases cluster in «المزيد».

## Contextual pages (must NOT get sidebar items)

- Dental chart / treatment plan → Doctor Workspace + Patient Profile.
- Pediatrics pack → Doctor Workspace + Patient Profile.
- Future OB/GYN specialty tools → specialty context only.

## Role-specific clutter

- Linked doctor sees purchases, suppliers, cash, settlements, doctors admin, settings.
- Reception sees labs/radiology/admin/finance depth they rarely use.
- Solo clinic still shows rooms/settlements.

## Patient profile problems

Too many peer tabs (timeline, prescriptions, labs, radiology, procedures, followups, dental, pediatrics, attachments, invoices). Need hub tabs with sections.

## Doctor workspace problems

Specialty/treatment/pediatrics/rx/bill tabs work, but lack a compact quick-action strip; alerts already OK.

## Mobile problems

Bottom nav always Reception + Billing; doctor/reception personas not distinguished; >5 conceptual destinations via menu only (OK) but primary 4 are not role-aware.

## Recommended IA

```
الرئيسية
التشغيل → استقبال، مواعيد، انتظار، (شاشة)
المرضى → مرضى، زيارات
الطبي → سجل، تحاليل، أشعة، إجراءات، متابعات
المالية → فواتير، (مصروفات/صندوق/تسويات)
المخزون → مخزون، مشتريات
الإدارة → أطباء، اختصاصات، خدمات، جداول، غرف
المزيد → مرفقات، موردون، تواصل، تقارير، إعدادات
```

Filter by permission + doctor-link + organization_mode. Routes unchanged.

## Files to modify

`workspace.html`, `clinics.css`, `clinics.js`, `patient-profile.js`, `service_dashboard.py` / bootstrap, new `nav.js`, tests + report.

## Risk assessment

Low backend risk (no model/schema changes). Primary risk: hiding a link a role still needs — mitigated by keeping URLs live and permission-gated only visually when permission exists; deep links remain.
