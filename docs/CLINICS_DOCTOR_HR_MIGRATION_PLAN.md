# Doctor Management Center — migration plan

## Current architecture inventory

- `clinic_doctor` already owns the clinical identity and already contains the nullable `employee_id` link. It does not contain a salary or HR leave balance.
- `employee` is the existing login/employee record and is the current HR salary source (`salary`, pay cycle fields and activation state).
- `hr_employee_profile` owns employee code, job title, employment type/status, hire and contract dates, department and annual leave entitlement.
- `hr_attendance` and `hr_leave_request` are the existing attendance and leave sources. Approved HR leave already creates HR attendance rows; no second doctor-leave workflow is required.
- `clinic_doctor_schedule` is the patient-booking schedule and supports multiple rows per weekday. It is intentionally separate from HR attendance.
- `clinic_doctor_time_off` is retained only for operational blocks (break, meeting, procedure, training or administrative time), not HR leave.
- appointments and visits keep their historical `doctor_id`; disabling or terminating a doctor must never delete these records.
- the current clinical commission implementation is legacy: a doctor-wide percentage (`clinic_doctor.commission_pct`), an optional service percentage (`clinic_service.doctor_commission_pct`) and standalone doctor settlements. HR payroll currently supports salary, allowances/deductions and salary payments, but it has no clinical commission ledger or payroll-run model.
- accounting currently posts payroll at payment time through `EmployeePayment`, `Expense` and treasury transactions. It does not yet have an approval-time salaries-payable journal workflow.

## Safe delivery sequence

1. Use the existing `clinic_doctor.employee_id` relationship and expose link/unlink actions with tenant and duplicate-link validation. Preserve unlinked doctors.
2. Build the doctors list and drawer from live clinic and HR queries. Load only list summaries initially; load HR, attendance, leave and payroll history lazily for one doctor.
3. Enforce doctor activation, HR employment status, approved HR leave, medical schedule/breaks and optional attendance requirements in the existing appointment availability guard.
4. Rename clinic time-off UI to “operational block” so it cannot be mistaken for HR leave. HR leave creation and approval remain in the existing HR workflow.
5. Keep salary read-only in Clinics and hide it unless the current user is an administrator or has `salary_sensitive_data.view`. Payroll payment continues through the existing HR route.
6. Add focused regression tests for doctor/employee linkage, HR-leave booking prevention, termination prevention, operational blocks, attendance-gated availability and privacy-safe summaries.

## Commission and payroll migration (requires a dedicated reviewed migration)

Do not reinterpret or delete `commission_pct` values in place. First profile every tenant database and classify values and surrounding usage. Values in the percentage range can only be migrated automatically when service/settlement evidence confirms they are percentages; ambiguous values such as `5000` require an explicit fixed-amount decision.

The read-only audit performed on 2026-09-02 found clinic tables in local test databases but no populated doctor, service-commission or doctor-settlement rows. Therefore there is no representative production value set in this workspace from which to infer a safe conversion rule. Production tenant data must be profiled before enabling a destructive backfill; the compatibility release continues reading the legacy percentage without modifying it.

The target design should add a normalized clinical compensation rule plus an immutable commission ledger with a unique source reference (for example doctor + visit + service/procedure). Ledger states should be `pending`, `approved`, `included_in_payroll`, `paid` and `reversed`. A payroll-period earning component must reference the ledger rows, and a uniqueness constraint must prevent the same source entering payroll twice. Existing `clinic_doctor_settlement` rows remain read-only historical records until reconciled and mapped.

Payroll-run approval and accounting liability posting should be introduced together. Approval posts salary expense to salaries payable once; payment clears the payable through the existing treasury/payment method; cancellation creates reversal entries rather than deleting history. This must not be layered onto the current payment-time expense posting without an idempotent cutover, or salary expense would be duplicated.

## Explicit non-goals of the compatibility release

- No duplicate salary, leave, attendance or payment fields are added to `clinic_doctor`.
- No automatic destructive commission conversion is performed.
- No historical appointment, visit, invoice, settlement or payment row is rewritten or deleted.
- No second HR employee, leave, attendance, payroll or payment workflow is created inside Clinics.
