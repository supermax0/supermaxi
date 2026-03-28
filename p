You are a senior full-stack engineer and QA automation expert.

Your task is to design and implement a complete end-to-end testing system for my existing Flask web application using Playwright.

⚠️ Constraints:

* DO NOT modify existing routes, database structure, or core business logic.
* Only ADD new files and minimal safe hooks if needed.
* The project already uses Flask, SQLite, and HTML templates.

---

## 🎯 Goals:

1. Install and configure Playwright properly
2. Create a clean scalable test structure
3. Automatically test key workflows in the system
4. Ensure tests are stable and readable
5. Generate HTML reports

---

## 📁 Project context:

* Backend: Flask
* Frontend: HTML, CSS, JS
* App runs on: http://localhost:5000
* Pages include:

  * Login page
  * Dashboard
  * Inventory
  * Orders
  * Customers

---

## 🧱 Tasks:

### 1. Setup Playwright

* Install @playwright/test
* Initialize config file
* Install browsers

---

### 2. Create folder structure:

Create:

tests/
auth/
dashboard/
inventory/
orders/

playwright.config.js

---

### 3. Write real tests:

#### ✅ Auth Test

* Open login page
* Fill username/password
* Submit
* Verify redirect to dashboard

#### ✅ Dashboard Test

* Ensure stats are visible
* Check charts loaded

#### ✅ Inventory Test

* Add new product
* Verify it appears in table

#### ✅ Orders Test

* Create order
* Verify it is saved

---

### 4. Use best practices:

* Use page.locator with IDs when possible
* Avoid timeouts/sleeps
* Use expect() assertions
* Group tests with test.describe

---

### 5. Add reusable helpers:

Create:
tests/utils/helpers.js

Include:

* login(page)
* createProduct(page)

---

### 6. Add config file:

playwright.config.js should include:

* baseURL: http://localhost:5000
* headless: false
* reporter: html

---

### 7. Add scripts to package.json:

"scripts": {
"test": "playwright test",
"test:ui": "playwright test --headed",
"report": "playwright show-report"
}

---

### 8. Generate example code for each test file

---

## 🧠 Important:

* Code must be clean and production-level
* Use async/await properly
* No pseudo code
* Everything must be runnable directly

---

## 🎁 Output format:

Return:

1. Folder structure
2. All files code (FULL)
3. Commands to run

Do NOT explain — just build the system.
