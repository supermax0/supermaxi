Develop an advanced Facebook Comment Listener system inside the existing autoposter backend.

IMPORTANT ARCHITECTURE RULES
- Do NOT change existing database structure unless adding new fields
- Do NOT break existing routes
- Do NOT modify working autoposter features
- Only ADD new modules

The system must automatically detect new Facebook posts/videos and fetch comments from them.

----------------------------------

GOAL

Create a background listener that:

1) Fetches all Facebook pages connected to the system
2) Automatically detects NEW posts or videos
3) Saves their IDs in database
4) Continuously fetches comments
5) Sends comments to AI workflow
6) Publishes automatic replies

----------------------------------

DATABASE

Use existing tables if possible:

AutoposterFacebookPage
AutoposterPost

If needed add:

last_comment_time
last_scan_time

Example schema extension:

AutoposterPost
- id
- page_id
- facebook_post_id
- created_time
- last_comment_time

----------------------------------

STEP 1
FETCH FACEBOOK PAGES

Load all Facebook pages stored in database.

Example:

pages = AutoposterFacebookPage.query.all()

----------------------------------

STEP 2
AUTO DETECT NEW POSTS AND VIDEOS

For every page call:

GET
https://graph.facebook.com/v19.0/{page-id}/posts

Fields required:

id
message
created_time
permalink_url
attachments

If the post contains video or reel the attachments will contain type=video.

Save every new post_id into AutoposterPost if not already stored.

----------------------------------

STEP 3
SAVE VIDEO IDs

If attachments contain video data extract:

video_id

Example:

attachments{
  media_type
  target{
     id
  }
}

Save video_id into database.

----------------------------------

STEP 4
FETCH COMMENTS

For every stored post call:

GET
/{post-id}/comments

fields:

id
message
from
created_time

----------------------------------

STEP 5
IGNORE OLD COMMENTS

Use last_comment_time.

Only process comments newer than the last processed comment.

----------------------------------

STEP 6
SEND COMMENT TO WORKFLOW

Each comment should produce event:

{
 "platform": "facebook",
 "page_id": "...",
 "post_id": "...",
 "comment_id": "...",
 "username": "...",
 "text": "...",
 "created_time": "..."
}

Send event to AI node.

----------------------------------

STEP 7
AI RESPONSE

Send comment text to OpenAI.

Example prompt:

"You are a social media assistant.
Reply to this Facebook comment politely and helpfully."

Generate response.

----------------------------------

STEP 8
POST REPLY

Publish reply using:

POST
/{comment-id}/comments

payload:

{
 "message": "AI reply"
}

----------------------------------

STEP 9
RUN BACKGROUND LISTENER

Create a background loop:

run_comment_listener()

It should run every:

30 seconds

----------------------------------

STEP 10
OPTIMIZATION

Limit scanning to:

last 10 posts per page.

----------------------------------

FILES TO CREATE

social_ai/
   facebook_listener.py
   comment_processor.py
   ai_responder.py

----------------------------------

facebook_listener.py responsibilities

- detect pages
- detect posts
- detect new videos
- fetch comments

----------------------------------

comment_processor.py responsibilities

- filter old comments
- send comment to workflow

----------------------------------

ai_responder.py responsibilities

- call OpenAI
- generate reply
- publish reply

----------------------------------

SECURITY

Handle:

- expired access tokens
- rate limits
- duplicate replies

----------------------------------

RESULT

System automatically:

- detects new videos
- detects new posts
- fetches comments
- replies automatically with AI

No manual configuration needed.