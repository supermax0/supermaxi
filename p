I have two Python Flask projects.

Project 1:
A deployed accounting SaaS platform running on a VPS with HTTPS and a domain.

Project 2:
A Facebook Auto Poster system that connects Facebook pages using OAuth and publishes posts.

Goal:
Integrate the Auto Poster system into the existing accounting platform as a module instead of running it separately.

Requirements:

1. Convert the Auto Poster project into a Flask Blueprint called "autoposter".
2. Mount it inside the main Flask app under the route:

/autoposter

Example URLs:

* /autoposter/dashboard
* /autoposter/pages
* /autoposter/create
* /autoposter/api/facebook/login
* /autoposter/api/facebook/callback

3. Move all routes from the Auto Poster project into the blueprint.

4. Use environment variables for Facebook credentials:
   FACEBOOK_APP_ID
   FACEBOOK_APP_SECRET

5. Update the OAuth redirect URL to:

https://mydomain.com/autoposter/api/facebook/callback

6. Ensure the Facebook OAuth flow:

* Login with Facebook
* Request permissions:
  pages_show_list
  pages_manage_posts
  pages_read_engagement
* Fetch pages via:
  /me/accounts

7. Store Facebook pages and tokens in the database.

8. Ensure the module works inside the existing authentication system of the SaaS platform.

9. Keep templates inside:

templates/autoposter/

and static files inside:

static/autoposter/

10. Do not break the existing accounting platform routes.

11. Provide the final structure of the project and the code needed to register the blueprint in the main Flask app.

Tech stack:
Python Flask, HTML, CSS, JavaScript, Facebook Graph API.

The solution must be production-ready and compatible with deployment on a VPS using HTTPS.
