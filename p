You are a senior Python backend engineer.

Project context:

The project is a Flask application located at:

/var/www/finora/supermaxi

The system contains a module called Autoposter that manages media uploads and publishing.

Important rules:

* DO NOT rename existing routes
* DO NOT change database schema
* DO NOT break existing features like POS, orders_manage, base.html
* Only repair the Autoposter media system

Current problems:

1. The endpoint
   /autoposter/api/media
   returns HTTP 500.

2. The endpoint
   /autoposter/api/media/upload
   also returns HTTP 500.

3. The frontend page
   /autoposter/media
   fails to upload images and videos.

4. The server is running behind nginx + gunicorn.

5. Gunicorn runs on:
   127.0.0.1:8000

6. Nginx proxies requests to gunicorn.

7. Media files should be stored in:

/var/www/finora/supermaxi/media

Tasks you must perform:

1. Locate the Flask routes responsible for:

/autoposter/api/media
/autoposter/api/media/upload

2. Fix all possible causes of 500 errors including:

* missing folders
* permission errors
* missing imports
* incorrect request.files usage
* invalid JSON responses
* login_required blocking API

3. Ensure the upload route supports:

jpg
png
webp
mp4
mov

4. Implement a safe upload system:

* verify file exists
* sanitize filename
* save file in media folder
* return JSON response

5. Create this API response format:

GET /autoposter/api/media

{
"success": true,
"media": [
{
"name": "file.jpg",
"url": "/media/file.jpg"
}
]
}

6. Fix upload endpoint:

POST /autoposter/api/media/upload

Return:

{
"success": true,
"url": "/media/filename.ext"
}

7. Automatically create missing folders:

media/
uploads/

8. Ensure Flask config contains:

MAX_CONTENT_LENGTH = 500MB

9. Ensure the project works with nginx large uploads.

10. Ensure JavaScript upload requests work without login redirects.

11. Add full error handling and logging.

12. Print exactly which file and line caused the original error.

Finally:

Output the corrected Python code for the media routes and any necessary fixes.



Act as a DevOps + Python expert.

Diagnose and repair a Flask production deployment.

Server stack:

Nginx
Gunicorn
Flask
Linux Ubuntu

Project path:

/var/www/finora/supermaxi

Tasks:

1. Check folder permissions
2. Verify media upload directory
3. Verify gunicorn process
4. Verify nginx upload limits
5. Verify Flask MAX_CONTENT_LENGTH
6. Detect any route causing HTTP 500
7. Repair broken API endpoints
8. Ensure media uploads work for images and videos
9. Ensure JSON responses instead of HTML errors
10. Provide exact code patches

Do not redesign the project.

Only repair errors safely.
