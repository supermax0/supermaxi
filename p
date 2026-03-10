You are a senior Flask + React engineer working on a SaaS project called **Finora**.

The system contains an **AI Agent Workflow Builder** (React frontend built with Vite) that loads workflow data from a Flask API.

Current issue:

The frontend is requesting:

GET /api/workflows?workflow_id=1

But Flask currently only exposes:

/workflows

So the browser receives:

404 NOT FOUND

Your task is to fix the backend so **both endpoints work** without breaking existing code.

Project structure:

Flask backend
/var/www/finora/supermaxi/routes/autoposter.py

React frontend
/static/ai_agent_frontend/src/modules/App.tsx

Steps:

1. Open `routes/autoposter.py`.

2. Locate the existing route that serves workflows:

@autoposter_bp.route("/workflows")

3. Modify it so it supports **both URLs**:

@autoposter_bp.route("/workflows")
@autoposter_bp.route("/api/workflows")

4. The function must read the query parameter:

workflow_id = request.args.get("workflow_id")

5. Return JSON with:

{
"nodes": [],
"edges": []
}

Example structure:

return {
"nodes": [
{"id":"1","type":"start","position":{"x":250,"y":50}}
],
"edges":[]
}

6. Do NOT change any unrelated routes.

7. Do NOT modify React code.

Goal:

Both of these must work:

/workflows?workflow_id=1
/api/workflows?workflow_id=1

Return HTTP 200 with JSON.

Also ensure the route uses `jsonify()` if Flask requires it.

Keep the change minimal and safe.
