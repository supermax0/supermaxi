You are working on a Flask SaaS project called Finora.

The project already has:
- Flask
- SQLAlchemy
- Multi-tenant architecture
- Blueprints
- Gunicorn + Nginx deployment
- APScheduler installed
- A module called autoposter

Your task is to implement a complete Facebook Auto Poster system.

Do NOT break existing routes or database structure.

------------------------------------------------

GOAL

Create a professional Facebook Auto Poster module that can:

1. Connect Facebook Pages
2. Store page access tokens
3. Create posts
4. Schedule posts
5. Automatically publish scheduled posts

------------------------------------------------

FEATURES TO IMPLEMENT

1) Facebook OAuth Login

Route:

/autoposter/connect-facebook

Redirect to Facebook OAuth:

https://www.facebook.com/v21.0/dialog/oauth

Scopes:

pages_show_list
pages_manage_posts
pages_read_engagement
pages_manage_metadata

------------------------------------------------

2) Facebook OAuth Callback

Route:

/autoposter/api/facebook/callback

Steps:

- receive OAuth code
- exchange code for access token
- request user pages:

GET https://graph.facebook.com/v21.0/me/accounts

Store pages in database.

------------------------------------------------

3) Database Models

Create models if missing:

AutoposterFacebookPage

fields:

id
tenant_id
page_id
page_name
access_token
created_at

-----------------------------------------------

AutoposterPost

fields:

id
tenant_id
page_id
message
image_url
status
scheduled_at
published_at
facebook_post_id
created_at

status values:

draft
scheduled
published
failed

------------------------------------------------

4) Create Post API

Route:

POST /autoposter/api/posts/create

Payload:

{
    page_id,
    message,
    image_url (optional),
    scheduled_at (optional)
}

If scheduled_at is empty -> publish immediately.

------------------------------------------------

5) Publish Post Function

Create function:

publish_post(page)

Call:

POST https://graph.facebook.com/{page_id}/feed

params:

message
access_token

Save returned post id.

------------------------------------------------

6) Scheduler

Use APScheduler.

Run every minute.

Function:

run_scheduled_posts_for_all_tenants()

Steps:

- load scheduled posts
- check scheduled_at <= now
- publish post
- update status to published

------------------------------------------------

7) Dashboard UI

Page:

/autoposter

Add pages management UI:

Button:

"ربط صفحة"

Show:

page_name
status
connected pages

-----------------------------------------------

Posts UI:

Create post form:

message
image
schedule date

Table:

scheduled posts
published posts

------------------------------------------------

8) Security

Use tenant_id filtering everywhere.

Example:

query.filter_by(tenant_id=current_tenant.id)

------------------------------------------------

9) Error Handling

Add try/except around Facebook API calls.

Log errors to console.

------------------------------------------------

10) Code Quality

- Follow blueprint structure
- Keep routes in routes/autoposter.py
- Models in models/autoposter.py
- Services in services/facebook_service.py

------------------------------------------------

OUTPUT

Generate:

- Flask routes
- SQLAlchemy models
- Facebook service class
- Scheduler integration
- Clean production-ready code