You are working on a Flask SaaS project called Finora.

The project already contains an autoposter module that publishes content to Facebook pages.

Refactor the autoposter system into a professional Media Library based architecture.

DO NOT break existing routes or database structure unless necessary.
Add new features cleanly using Flask Blueprints and SQLAlchemy.

-------------------------------------------------------

MAIN GOAL

Create a robust autoposter system with:

1. Media Library
2. Video uploads
3. Image uploads
4. Scheduled posts
5. Facebook publishing
6. Clean UI

-------------------------------------------------------

MEDIA LIBRARY SYSTEM

Create a media manager.

Route:

/autoposter/media

Features:

• upload video
• upload images
• preview media
• select media when creating post

-------------------------------------------------------

DATABASE MODELS

Create new model:

AutoposterMedia

fields:

id
tenant_id
media_type (image | video)
file_name
file_path
file_size
created_at

-------------------------------------------------------

POST MODEL UPDATE

Update AutoposterPost model.

Add fields:

media_id
post_type
caption

post_type values:

post
video
reel
story

-------------------------------------------------------

UPLOAD API

Route:

POST /autoposter/api/media/upload

Requirements:

• accept multipart/form-data
• store file in:

uploads/media/

• detect media type

Example:

if file.content_type.startswith("video"):
    media_type = "video"
else:
    media_type = "image"

Save media record to database.

-------------------------------------------------------

FRONTEND MEDIA PAGE

Create page:

templates/autoposter/media_library.html

Display media grid:

• video preview using <video>
• image preview using <img>

Example:

<video controls width="200"></video>

-------------------------------------------------------

POST CREATION PAGE

Route:

/autoposter/create

Features:

• text caption
• page selection
• media selection from library
• scheduling time

Example UI:

Media selector dropdown.

-------------------------------------------------------

FACEBOOK PUBLISHING

Images must use:

POST /{page-id}/photos

Videos must use:

POST /{page-id}/videos

Example video publish:

url = f"https://graph.facebook.com/v21.0/{page_id}/videos"

files = {
    "source": open(video_path, "rb")
}

data = {
    "description": caption,
    "access_token": page_token
}

requests.post(url, data=data, files=files)

-------------------------------------------------------

SCHEDULER

Use APScheduler.

Run every minute.

Function:

run_scheduled_posts_for_all_tenants()

Steps:

1. find scheduled posts
2. scheduled_at <= now
3. publish post
4. update status

status values:

draft
scheduled
published
failed

-------------------------------------------------------

FILE VALIDATION

Limit uploads:

Images:
jpg
png
webp

Videos:
mp4
mov

Max size:

500MB

-------------------------------------------------------

UI IMPROVEMENTS

Add new sidebar section:

Autoposter
   ├── Dashboard
   ├── Media Library
   ├── Create Post
   └── Scheduled Posts

-------------------------------------------------------

CODE STRUCTURE

Routes:

routes/autoposter_media.py
routes/autoposter_posts.py

Services:

services/facebook_service.py

Models:

models/autoposter.py

-------------------------------------------------------

OUTPUT

Generate production ready code.

Ensure media uploads are reliable and large video uploads do not break the system.