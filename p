Fix the integration between the React (Vite) build and the Flask Autoposter page `/autoposter/ai-agent`.

Problem:
The React project inside `static/ai_agent_frontend` is built successfully with Vite and generates files inside:

static/ai_agent_frontend/dist/
static/ai_agent_frontend/dist/assets/

Example build output:
dist/index.html
dist/assets/index.css
dist/assets/ai-agent.js

However, the Flask template currently loads old files like:

styles.css
ai-agent.js

which causes the layout to break.

Goal:
Update the Flask template that renders `/autoposter/ai-agent` so it correctly loads the built Vite files.

Tasks:

1. Find the template responsible for `/autoposter/ai-agent` (likely inside `templates/autoposter/ai_agent.html` or similar).

2. Remove any references to old static files like:

   * styles.css
   * ai-agent.js (outside dist)

3. Replace them with the correct Vite build assets:

<link rel="stylesheet" href="/static/ai_agent_frontend/dist/assets/index.css">

<script type="module" src="/static/ai_agent_frontend/dist/assets/ai-agent.js"></script>

4. Ensure the template contains a root element for React:

<div id="root"></div>

5. If necessary, update the Flask route to serve the page correctly:

@app.route("/autoposter/ai-agent")
def ai_agent():
return render_template("autoposter/ai_agent.html")

6. Ensure Flask static paths correctly resolve to:

/static/ai_agent_frontend/dist/assets/

7. Do not modify the React code. Only fix the Flask template integration.

Expected result:
The AI Agent Builder page loads the React Flow UI correctly with proper CSS and layout, using the Vite production build files.
