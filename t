Build a multi-tenant SaaS system using Flask where each tenant (company) has a selectable business type.

Add a field in the Tenant model:

* business_type: "general" or "beauty_center"

From the Super Admin panel:

* Allow selecting the business type when creating/editing a company.

System behavior must dynamically change based on business_type:

====================
FOR GENERAL COMPANY
===================

Keep existing features:

* Sales
* Orders
* POS
* Inventory
* Shipping
* Customers

====================
FOR BEAUTY CENTER
=================

Hide:

* Orders
* Shipping
* Delivery
* E-commerce features

Add new modules:

1. Appointments System

* Book appointment with:

  * customer
  * service
  * date/time
  * status (pending, done, cancelled)

2. Services Module

* Define services like:

  * Facial
  * Laser
  * Peeling
* Each service has:

  * price
  * duration

3. Service Products Mapping

* Each service consumes products
* Define:

  * product_id
  * amount_used

4. Session Execution

* When appointment is marked as DONE:

  * automatically deduct product quantities from inventory

5. Product Enhancement

* Add fields:

  * skin_type
  * usage_type
  * requires_patch_test

6. Inventory Enhancement

* Add:

  * expiry_date
  * opened_date
  * batch_number

7. Customer History

* Track:

  * services used
  * products used
  * notes

8. Alerts

* Low stock
* Expiry warning
* High consumption

====================
UI BEHAVIOR
===========

Sidebar must change dynamically:

If beauty_center:

* Show:

  * Appointments
  * Services
  * Sessions
  * Clients
  * Inventory (enhanced)

If general:

* Show:

  * Sales
  * Orders
  * POS
  * Shipping

====================
IMPORTANT
=========

* Do NOT break existing routes
* Add features as extensions
* Keep backward compatibility
* Use clean modular Flask Blueprints
