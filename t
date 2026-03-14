You are a senior Python backend engineer and DevOps expert.

The project is a production Flask application running behind:

* Nginx
* Gunicorn
* Linux Ubuntu

Project path:

/var/www/finora/supermaxi

Domain:

https://finora.company

Gunicorn runs on:

127.0.0.1:8000

The system includes an Autoposter module with routes such as:

/autoposter/media
/autoposter/upload
/autoposter/api/media
/autoposter/api/media/upload

Current problems:

1. The page

/autoposter/upload

sometimes returns:

ERR_SSL_PROTOCOL_ERROR

2. Upload requests fail.

3. Some API endpoints return 500 errors.

Your tasks:

1. Scan the entire Flask project.
2. Locate the routes responsible for Autoposter upload.
3. Fix all causes of HTTP 500 errors.
4. Fix any redirect loops or HTTPS mismatches.
5. Ensure uploads work correctly for:

jpg
png
webp
mp4
mov

6. Ensure uploads are saved in:

/var/www/finora/supermaxi/media

7. Automatically create missing folders if needed.

8. Ensure Flask config includes:

MAX_CONTENT_LENGTH = 500MB

9. Ensure upload routes return JSON responses instead of HTML errors.

10. Ensure routes do not redirect to login when accessed by JavaScript API.

11. Ensure compatibility with nginx proxy.

12. Print the corrected Python code for all media routes.

13. Ensure the upload endpoint works with FormData in JavaScript.

14. Add proper exception handling and logging.

Important rules:

* DO NOT rename existing routes
* DO NOT change database schema
* DO NOT break existing modules
* Only repair Autoposter upload and media API

Finally output:

1. The corrected Flask route code.
2. Any necessary configuration fixes.
3. Any missing folder creation logic.
