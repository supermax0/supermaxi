You are working inside a Flask project.

Problem:
The React Workflow Builder calls:

/workflows?workflow_id=1

but the server redirects to /login instead of returning JSON.

Goal:
Create a proper API endpoint that returns workflow nodes and edges in JSON so the ReactFlow UI can render them.

Steps:

1. Search the project for any existing route related to "workflows".
2. If none returns JSON, add a new Flask route.

Add this route to the main Flask app (app.py) or an appropriate routes file:

```python
from flask import jsonify, request
from flask_login import current_user

@app.route("/workflows")
def workflows_api():
    if not current_user.is_authenticated:
        return jsonify({"error": "not_authenticated"}), 401

    workflow_id = request.args.get("workflow_id")

    return jsonify({
        "nodes": [
            {"id":"1","type":"start","position":{"x":250,"y":50}},
            {"id":"2","type":"ai","position":{"x":250,"y":200}},
            {"id":"3","type":"image","position":{"x":250,"y":350}},
            {"id":"4","type":"caption","position":{"x":250,"y":500}},
            {"id":"5","type":"publisher","position":{"x":250,"y":650}},
            {"id":"6","type":"scheduler","position":{"x":250,"y":800}},
            {"id":"7","type":"comment-listener","position":{"x":250,"y":950}},
            {"id":"8","type":"auto-reply","position":{"x":250,"y":1100}},
            {"id":"9","type":"end","position":{"x":250,"y":1250}}
        ],
        "edges":[
            {"id":"e1","source":"1","target":"2"},
            {"id":"e2","source":"2","target":"3"},
            {"id":"e3","source":"3","target":"4"},
            {"id":"e4","source":"4","target":"5"},
            {"id":"e5","source":"5","target":"6"},
            {"id":"e6","source":"6","target":"7"},
            {"id":"e7","source":"7","target":"8"},
            {"id":"e8","source":"8","target":"9"}
        ]
    })
```

3. Ensure the endpoint returns JSON and never redirects to /login.
4. Save the file.
5. Restart Gunicorn:

```bash
pkill -f gunicorn
venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 app:app &
```

Expected result:

Calling

curl http://127.0.0.1:8000/workflows?workflow_id=1

should return JSON with nodes and edges instead of redirecting to /login.

This will allow the React Workflow Builder to display all nodes.
