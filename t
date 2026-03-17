@codebase

You are a senior backend engineer specializing in Meta (Facebook) Graph API.

Modify the Facebook publishing system in this repository to support two visibility modes:

1) Public (visible on Page Timeline)
2) Hidden (Only me / hidden from page)

Tasks:

1. Locate all Facebook publishing logic in the repository, especially:

- modules/publisher/services/facebook_service.py
- platforms/facebook.py
- modules/publisher/services/scheduler_service.py
- modules/publisher/api/posts_api.py
- static/publisher/js/publisher.js

2. Add a new field called:

visibility

Possible values:
- "public"
- "hidden"

3. Modify all Facebook publishing payloads so that:

If visibility == "public"
    published = True

If visibility == "hidden"
    published = False

4. Apply this logic to all publishing endpoints:

TEXT POST
POST /{page_id}/feed

PHOTO POST
POST /{page_id}/photos

VIDEO POST
POST /{page_id}/videos

5. Ensure the payload always includes:

published: True or False

6. Ensure the system NEVER publishes using:
- /me/feed
- user access tokens

Only Page publishing with:
page_id + page access token.

7. Update backend functions so they accept the visibility parameter.

Example Python logic:

published = True if visibility == "public" else False

payload = {
    "message": text,
    "access_token": page_token,
    "published": published
}

8. Update the frontend UI (publisher.js) to include a visibility selector:

Radio buttons:

○ Show on Page (Public)
○ Hidden / Only me

9. Ensure the selected visibility value is sent in the API request.

10. Show the exact code modifications needed in this repository.

Do not give theoretical explanations.
Only show the code changes.