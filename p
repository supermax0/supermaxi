You are a senior Python backend engineer and DevOps specialist.

I have a production web application deployed with:

* Flask
* Gunicorn
* Nginx
* JavaScript frontend
* Ubuntu server
* Domain: finora.company
* Project path: /var/www/finora/supermaxi

The system contains an AutoPoster module that currently uses:

POST /autoposter/api/posts

This endpoint uploads video and creates the post at the same time, which causes multiple issues.

---

## PROBLEMS WE EXPERIENCED

1. Video upload sometimes fails.
2. POST /autoposter/api/posts returns 500 errors.
3. Requests redirect to /login because session cookies are missing.
4. fetch() does not include cookies.
5. Logout does not properly clear sessions.
6. Gunicorn sometimes fails due to port 8000 conflicts.
7. Large uploads break the API.
8. Flask logs are not detailed enough to debug errors.
9. Uploads directory sometimes missing.
10. Nginx upload configuration needs verification.

---

## GOAL

Redesign the video upload architecture to be production-safe.

Instead of uploading video in the same request as post creation, implement a two-step process.

---

## NEW ARCHITECTURE

Step 1 – Upload video:

POST /autoposter/api/upload

Accept multipart upload:

request.files["file"]

Save uploaded video to:

/var/www/finora/uploads/videos

Return JSON:

{
"url": "/uploads/videos/filename.mp4"
}

---

Step 2 – Create post:

POST /autoposter/api/posts

Accept JSON:

{
"text": "...",
"video_url": "/uploads/videos/file.mp4",
"page_ids": [123],
"post_type": "post"
}

---

## BACKEND REQUIREMENTS

1. Implement new route:

/autoposter/api/upload

2. Ensure directory is created automatically if missing.

3. Add upload size limit:

200MB

4. Validate file types:

video/mp4
video/quicktime

5. Add logging for errors using:

current_app.logger.exception()

6. Ensure the posts API works without uploading files directly.

7. Improve session handling:

SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_DOMAIN = ".finora.company"

8. Fix logout logic:

session.clear()
logout_user()
delete_cookie("session")

---

## FRONTEND REQUIREMENTS

Rewrite the upload flow in JavaScript.

Step 1 – upload video:

const fd = new FormData()
fd.append("file", videoFile)

await fetch("/autoposter/api/upload", {
method: "POST",
body: fd,
credentials: "include"
})

Step 2 – create post:

await fetch("/autoposter/api/posts", {
method: "POST",
headers: { "Content-Type": "application/json" },
credentials: "include",
body: JSON.stringify({
text,
video_url,
page_ids
})
})

---

## NGINX CONFIGURATION

Ensure Nginx supports large uploads:

client_max_body_size 200M;

Serve uploaded videos:

location /uploads/videos/ {
alias /var/www/finora/uploads/videos/;
access_log off;
expires 30d;
}

---

## GUNICORN CONFIGURATION

Use production-safe configuration.

If port conflicts occur, switch to Unix socket:

/run/finora.sock

---

## OUTPUT REQUIRED

Generate:

1. Flask upload route
2. Updated posts route
3. Updated logout route
4. JavaScript upload logic
5. Nginx configuration
6. Gunicorn configuration
7. Directory creation logic
8. Error logging improvements
9. A diagnostic bash script for debugging the API

The final solution must be production-ready and stable.
