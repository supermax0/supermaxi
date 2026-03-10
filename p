You are a senior full-stack engineer specialized in Flask + React + Vite deployments.

Your task is to diagnose and fix why the AI Agent Workflow Builder works in development but appears broken in production.

Project architecture:

Backend:
Flask
Gunicorn
systemd service

Server path:
/var/www/finora/supermaxi

Frontend:
React + Vite

Frontend source directory:
static/ai_agent_frontend/

Built frontend output:
static/ai_agent_frontend/dist/

Current build assets:
static/ai_agent_frontend/dist/assets/ai-agent.js
static/ai_agent_frontend/dist/assets/index.css

Problem description:

In development the workflow builder renders nodes correctly.

In production the page loads but the workflow canvas shows only the Start node and the UI looks incomplete.

Browser DevTools Network tab shows that only styles.css loads and the main Vite bundle ai-agent.js is not loaded.

Goal:

Ensure the Flask template correctly loads the Vite build assets so the React workflow builder runs in production exactly as in development.

Steps to perform:

1. Locate the Flask template that renders the AI Agent page:
   likely templates/ai_agent.html or templates/autoposter/ai_agent.html

2. Ensure the template loads the built assets using Flask static routing.

Add the following to the template:

<link rel="stylesheet" href="{{ url_for('static', filename='ai_agent_frontend/dist/assets/index.css') }}">

<div id="root"></div>

<script type="module"
src="{{ url_for('static', filename='ai_agent_frontend/dist/assets/ai-agent.js') }}">
</script>

3. Ensure the React app mounts into the correct element:

document.getElementById("root")

4. Verify that the static directory structure is correct:

static/
ai_agent_frontend/
dist/
assets/
ai-agent.js
index.css

5. Add debugging logs to confirm that the React workflow initializes.

6. Ensure the autoposter route returns the correct template.

Example Flask route:

@app.route("/autoposter/ai-agent")
def ai_agent():
return render_template("ai_agent.html")

7. Ensure Gunicorn serves static files correctly through Flask.

8. Verify that visiting:

/static/ai_agent_frontend/dist/assets/ai-agent.js

returns HTTP 200.

9. If the React bundle is missing, create a build step:

cd static/ai_agent_frontend
npm install
npm run build

10. Ensure the dist folder is committed to Git and deployed to the server.

11. Ensure the workflow builder initializes automatically when the page loads.

Expected result:

Opening

/autoposter/ai-agent

should load:

index.css
ai-agent.js

and the full AI Agent Workflow Builder UI should render with nodes such as:

Start
AI Agent
Image Generator
Caption Generator
Publisher
Scheduler
Comment Listener
Auto Reply
End

At the end provide:

• Files modified
• Exact template fix
• Any missing static assets
• Deployment steps
