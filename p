You are a senior Python + Flask + React debugging engineer.

I have a Flask SaaS project called **Finora** that contains an AI Agent Workflow Builder (React + Vite frontend) served inside Flask.

Current problem:
The frontend is requesting the wrong API path:

/autoposter/api/api/api/workflows

This causes:

404 NOT FOUND

The correct endpoint should be:

/autoposter/api/workflows

Project structure:

Flask backend
React frontend built with Vite

Relevant folders:

/var/www/finora/supermaxi/routes/autoposter.py
/var/www/finora/supermaxi/static/ai_agent_frontend/src/modules/App.tsx

Current issues:

1. React fetch path duplicates `/api`
2. Flask blueprint may also contain `/api`
3. Combined result becomes `/api/api/api`
4. Workflow API therefore returns 404

Your task is to fix the architecture cleanly.

Steps:

1. Fix the Flask Blueprint inside `routes/autoposter.py`

Blueprint must be:

autoposter_bp = Blueprint(
"autoposter",
**name**,
url_prefix="/autoposter"
)

NOT `/autoposter/api`.

2. Add a proper API route inside the same blueprint:

@autoposter_bp.route("/api/workflows", methods=["GET"])
def api_workflows():

```
workflow_id = request.args.get("workflow_id")

return {
    "nodes": [],
    "edges": []
}
```

3. Fix the React fetch path inside:

static/ai_agent_frontend/src/modules/App.tsx

Find any of these:

fetch("workflows")
fetch("/workflows")
fetch("/api/api/workflows")

Replace them with:

fetch(`/autoposter/api/workflows?workflow_id=${workflowId}`)

4. Ensure there is NO duplicated `/api`.

5. Do not modify unrelated code.

6. After fixing, output the exact commands needed to rebuild the frontend:

cd static/ai_agent_frontend
npm install
npm run build

And restart gunicorn:

pkill -9 -f gunicorn
venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 app:app

Goal:

Final API call from browser must be:

/autoposter/api/workflows?workflow_id=1

and return HTTP 200 with JSON.

Make minimal clean changes.
