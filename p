You are a senior Python backend engineer specializing in Flask, SQLAlchemy, and production debugging.

I have a Flask-based application called Finora with an Autoposter system. The endpoint:

POST /autoposter/api/posts

sometimes returns HTTP 500 errors. The frontend successfully uploads media (video/image), but the backend fails when inserting the post into the database or processing the request.

System details:

- Backend: Python Flask
- Server: Ubuntu VPS
- App server: Gunicorn
- Reverse proxy: Nginx
- Database: SQLite (multi-tenant)
- ORM: SQLAlchemy
- Media uploads: images and videos
- Project path:
  /var/www/finora/supermaxi
- Tenants database folder:
  /var/www/finora/supermaxi/tenants/
- Upload folders:
  uploads/videos
  uploads/images

Tables include:
autoposter_posts
autoposter_templates
autoposter_notifications
autoposter_facebook_pages

Common errors include:

- SQLAlchemy IntegrityError
- NOT NULL constraint failed
- Invalid media upload
- Video upload works but database insertion fails
- Missing or None values in request.form
- Missing directories for uploads
- Gunicorn timeout or Nginx upload limits

Your task:

1. Design a robust Flask endpoint implementation for:

   def api_posts_create():

2. Requirements for the implementation:

   - Accept form-data with:
        page_id
        page_name
        content
        image
        video
        scheduled_at
   - Handle missing fields safely
   - Prevent database NOT NULL errors
   - Save uploaded files securely
   - Support scheduled posts
   - Return clear JSON responses
   - Log errors properly
   - Avoid crashing with HTTP 500

3. Implement safe file upload:

   - use werkzeug.secure_filename
   - create upload folders if missing
   - validate file extensions
   - generate unique filenames
   - return relative media URLs

4. Implement validation:

   - verify allowed extensions
   - verify scheduled datetime
   - prevent empty inserts

5. Database insertion:

   - insert into AutoposterPost model
   - ensure nullable-safe values
   - handle SQLAlchemy exceptions

6. Add structured error handling:

   try/except blocks
   logger.exception
   meaningful JSON error responses

7. Ensure compatibility with SQLite multi-tenant setup.

8. Provide production-ready code including:

   - full Flask route
   - helper functions
   - safe media saving
   - logging
   - error handling

9. Also include optional improvements:

   - background queue support
   - retry logic
   - media compression with ffmpeg
   - rate limit protection

Output format:

1) Full Python code for api_posts_create
2) helper functions
3) example SQLAlchemy model (AutoposterPost)
4) explanation of how it prevents IntegrityError
5) recommended production improvements

Make the implementation secure, clean, and production-ready.