You are a senior Python/Flask engineer working on a production system.

Project context:
This is a large Flask application called Finora with multiple modules (POS, inventory, dashboard). 
We recently added a new module called "publisher" for Facebook publishing.

The module structure:

modules/
  publisher/
    api/
      settings_api.py
      pages_api.py
      media_api.py
      posts_api.py
    models/
      publisher_settings.py
      publisher_page.py
      publisher_media.py
      publisher_post.py
    services/
      facebook_service.py
      media_service.py
      ai_service.py
      scheduler_service.py
    routes.py

The module is registered in app.py with:

app.register_blueprint(publisher_bp, url_prefix="/publisher")

Problem symptoms:

1) Frontend errors:
Unexpected token '<'
Failed to load resource: 500

2) API endpoints returning HTML redirect instead of JSON:
GET /publisher/api/settings
GET /publisher/api/pages
GET /publisher/api/media

Instead of JSON they return:

<!doctype html>
<title>Redirecting...</title>

Which means the request is redirected to /login.

3) The application has a global login guard implemented using:

@app.before_request

which redirects all unauthenticated users to /login.

The publisher APIs are being blocked by this guard.

4) Frontend JavaScript expects JSON responses and crashes when HTML is returned.

Required task:

Fix the authentication guard so that:

- Publisher API routes work correctly
- They return JSON instead of redirect HTML
- Without breaking the existing login system

Important constraints:

- DO NOT modify existing POS, inventory, accounting modules
- Changes must be isolated
- Maintain production safety

Implementation requirements:

1) Update the login middleware in app.py so that API routes under:

/publisher/api/

are allowed to return JSON instead of redirecting to login.

2) If user is not authenticated, the API should return:

return jsonify({"success": False, "message": "Unauthorized"}), 401

instead of redirect.

3) Ensure all publisher API routes return JSON responses.

4) Verify the following endpoints:

GET /publisher/api/settings
POST /publisher/api/settings
GET /publisher/api/pages
GET /publisher/api/media
POST /publisher/api/posts/create

5) Ensure that errors are always returned as JSON:

{
 "success": false,
 "message": "error message"
}

6) Add proper logging for debugging:

current_app.logger.error(traceback.format_exc())

7) Ensure that the frontend will never receive HTML for API requests.

8) Provide the corrected code for:

- app.py login middleware
- example publisher API route

Goal:

After the fix:

/publisher/api/settings should return:

{
 "success": true,
 "settings": {...}
}

instead of redirecting to /login.