You are a senior Flask backend engineer.

Project context:

The project is a production Flask application located at:

/var/www/finora/supermaxi

It runs behind:

Nginx
Gunicorn

Domain:

https://finora.company

The system contains an Autoposter module.

Current problem:

Uploading images works successfully (HTTP 200),
but uploaded images do NOT appear in the media table.

The frontend page calls this endpoint:

GET /autoposter/api/media

However the project currently has NO implementation for this endpoint.

Your task is to safely repair the system.

Important rules:

* Do NOT rename existing routes
* Do NOT modify the database schema
* Do NOT break existing modules (POS, orders, dashboard)
* Only repair the Autoposter media system

Tasks:

1. Scan the Flask project structure.
2. Check if a route exists for:

/autoposter/api/media

3. If it does NOT exist, create a new Blueprint file:

routes/autoposter_api.py

4. Implement the endpoint:

GET /autoposter/api/media

This endpoint must:

• scan media directories
• return all uploaded files

Folders to scan:

media/
uploads/images/
uploads/videos/

All folders are inside:

/var/www/finora/supermaxi

5. The API must return JSON like:

{
"success": true,
"media": [
{
"name": "image.png",
"url": "/uploads/images/image.png"
}
]
}

6. Register the blueprint in app.py safely.

7. Ensure the API never crashes if folders are missing.

8. Add automatic folder creation if needed.

9. Ensure Nginx can serve uploaded files correctly.

Example nginx paths:

location /uploads {
alias /var/www/finora/supermaxi/uploads;
}

location /media {
alias /var/www/finora/supermaxi/media;
}

10. Print the final corrected Python code and configuration changes.

Goal:

After the fix:

• Uploading an image works
• The image appears in the media library table
• The API returns all uploaded files correctly.
