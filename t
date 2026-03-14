You are a senior full-stack engineer and system architect.

Your task is to design and implement a **professional Facebook publishing system** inside an existing Flask web application.

The project is located at:

/var/www/finora/supermaxi

The current stack is:

Python
Flask
Gunicorn
Nginx
SQLite (or PostgreSQL optional)
HTML / CSS / JavaScript

The system must be built from scratch because the old autoposter module has been completely removed.

IMPORTANT RULES

• Do NOT modify existing modules such as POS, inventory, dashboard.
• Build the publishing system as a **separate module**.
• Use Flask Blueprints.
• Ensure clean architecture and maintainability.
• All APIs must return JSON.
• The system must support **Facebook only for now**.

---

SYSTEM GOALS

Create a **Professional Facebook Publishing Platform** with:

• Media library
• Post creation
• Multi-page publishing
• Scheduled posts
• AI content assistant
• High quality media upload
• Modern UI

---

ARCHITECTURE

Create a new module:

modules/publisher/

Structure:

modules/publisher/
api/
posts_api.py
media_api.py
pages_api.py
ai_api.py
services/
facebook_service.py
media_service.py
ai_service.py
scheduler_service.py
models/
post_model.py
media_model.py
page_model.py
templates/
publisher/
dashboard.html
create_post.html
media_library.html
static/
publisher/
css/
js/
components/
routes.py

---

FEATURES

1. FACEBOOK PAGE CONNECTION

Users must be able to:

• connect Facebook account
• fetch available pages
• store page access tokens securely
• list pages in UI

Use Facebook Graph API.

Store:

page_id
page_name
page_token

---

2. MEDIA LIBRARY

Create a professional media library.

Features:

• upload images
• upload videos
• preview media
• search media
• grid view
• delete media
• drag and drop upload

Supported formats:

jpg
png
webp
mp4
mov

Max upload size:

500MB

Storage location:

/var/www/finora/supermaxi/media

Structure:

media/
images/
videos/

Database fields:

id
filename
type
size
created_at

---

3. MEDIA UPLOAD SYSTEM

Implement robust upload handling.

Requirements:

• progress bar
• drag and drop
• file validation
• automatic folder creation
• error handling
• preview generation

Return JSON:

{
"success": true,
"url": "/media/images/file.jpg"
}

---

4. POST CREATION

Create a page:

/publisher/create

Features:

• write post text
• select pages
• attach media
• preview post
• schedule post

UI must look modern and clean.

---

5. MULTI PAGE PUBLISHING

Allow selecting multiple pages.

Publishing modes:

• publish now
• schedule later

---

6. SCHEDULER

Scheduled posts must be stored and executed by a background worker.

Use:

APScheduler

Store:

post_id
publish_time
status

---

7. FACEBOOK PUBLISHING SERVICE

Create a service:

services/facebook_service.py

Responsibilities:

• publish text posts
• publish image posts
• publish video posts
• error handling
• retry logic

---

8. AI CONTENT ASSISTANT

Create AI integration.

Features:

• generate post text
• rewrite text
• generate hashtags
• improve marketing tone

Endpoint:

POST /publisher/api/ai/generate

Input:

topic
tone
length

Return:

AI generated text.

---

9. PROFESSIONAL UI

Create a modern design.

Style:

• dark modern dashboard
• responsive layout
• sidebar navigation
• card components
• media grid
• upload area with drag & drop

Use:

Vanilla JS or lightweight framework.

---

10. API ENDPOINTS

Required APIs:

GET  /publisher/api/media
POST /publisher/api/media/upload
DELETE /publisher/api/media/<id>

GET  /publisher/api/pages

POST /publisher/api/posts/create
POST /publisher/api/posts/schedule

POST /publisher/api/ai/generate

---

11. ERROR HANDLING

All APIs must return structured JSON:

{
"success": false,
"message": "error description"
}

---

12. LOGGING

Create logging system.

Logs stored in:

logs/publisher.log

Log:

• publish attempts
• errors
• API calls

---

13. SECURITY

Implement:

• file validation
• token protection
• max upload limits
• rate limiting for APIs

---

14. NGINX CONFIGURATION

Ensure nginx supports uploads:

client_max_body_size 500M;

Serve media:

location /media {
alias /var/www/finora/supermaxi/media;
}

---

15. PERFORMANCE

Use:

• async requests
• caching for media lists
• background publishing jobs

---

FINAL OUTPUT

The AI must generate:

• complete folder structure
• Flask routes
• services
• models
• media upload system
• Facebook integration
• AI assistant
• frontend UI
• scheduler
• logging

The result must be a **production-ready Facebook publishing platform**.


ملاحظات مهمة لبناء النظام صح من البداية

افصل النظام في module مستقل حتى لا يكسر مشروعك.

اجعل النشر يتم عبر service layer وليس داخل routes.

استخدم scheduler للنشر المجدول.

اجعل media library مشتركة بين كل المنشورات.