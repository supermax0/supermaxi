You are a senior backend engineer specialized in Meta Graph API.

Audit and fix the Facebook publishing implementation in this project.

Goal:
Ensure posts published to Facebook Pages appear publicly in the Page Timeline and are not created as hidden posts, reels, or unpublished media.

Tasks:

1. Locate all Facebook publishing code in the project:
   - platforms/facebook.py
   - modules/publisher/services/facebook_service.py
   - scheduler_service.py
   - workflow_engine.py
   - any other file calling Graph API.

2. Verify the correct Graph API endpoints are used:

TEXT POSTS:
POST https://graph.facebook.com/v19.0/{page_id}/feed

PHOTO POSTS:
POST https://graph.facebook.com/v19.0/{page_id}/photos

VIDEO POSTS:
POST https://graph.facebook.com/v19.0/{page_id}/videos

3. Ensure publishing always uses:
- page_id (never "me")
- Page Access Token
- published=true

4. Ensure videos are published as normal posts, not reels.

Video upload must include:
- description
- published=true
- access_token
- source file

5. Ensure photo uploads use:

POST /{page_id}/photos
caption=message
published=true

6. Detect and fix any logic that may cause:
- publishing reels instead of posts
- unpublished posts
- dark posts
- publishing to user profile instead of page
- missing published flag
- incorrect endpoint

7. Improve success detection logic:
Treat response as success if:
- HTTP status = 200
- response contains "id" OR "post_id"

8. Add safe JSON parsing for API responses.

9. Add debug logging to show:
- page_id
- endpoint used
- response from Facebook API

10. Provide the corrected code snippets for:
- text publishing
- photo publishing
- video publishing

Do not give theoretical explanations.
Only show exact code fixes needed in this repository.