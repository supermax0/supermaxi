@codebase

You are a senior backend engineer specializing in Meta (Facebook) Graph API.

Audit the entire repository and locate all Facebook publishing logic.

Focus especially on:

- platforms/facebook.py
- modules/publisher/services/facebook_service.py
- modules/publisher/services/scheduler_service.py
- workflow_engine.py
- routes/publish_api.py
- any file sending requests to graph.facebook.com

Problem:
Posts created by this system appear in the Page Activity Log as:

"Hidden from Page" or "Only me"

This means the system is creating hidden page posts instead of normal timeline posts.

Tasks:

1. Find any place where Facebook posts are created with:
   - published=false
   - unpublished_content_type
   - or any flag that creates hidden posts.

2. Ensure all publishing requests explicitly send:

published=true

3. Ensure correct Graph API endpoints are used:

TEXT POST
POST https://graph.facebook.com/v19.0/{page_id}/feed

PHOTO POST
POST https://graph.facebook.com/v19.0/{page_id}/photos

VIDEO POST
POST https://graph.facebook.com/v19.0/{page_id}/videos

4. Ensure the system NEVER publishes using:
   - /me/feed
   - user access tokens
   - ad or dark post endpoints

5. Ensure posts appear publicly in the Page Timeline.

6. Improve success detection:
A post should be considered successful if:

HTTP status = 200
AND response contains either:
"id" OR "post_id"

7. Add debug logging showing:
- page_id
- endpoint used
- payload sent
- response from Facebook API

8. Show the exact lines in the repository that cause hidden posts.

9. Provide corrected code snippets that guarantee the post appears publicly on the Page Timeline.

Do not explain theory.
Only show exact bugs and corrected code.