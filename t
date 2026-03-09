Continue implementing the AI Agent / Visual Workflow Builder inside the Autoposter project.

The system already contains:

* Backend models (Agent, AgentWorkflow, AgentExecution, AgentExecutionLog)
* REST APIs for agents and workflows
* Basic workflow execution engine
* React + React Flow frontend under static/ai_agent_frontend
* A page at /autoposter/ai-agent rendering a basic React Flow canvas

Now implement the next stage: a **fully functional Node Editor**.

---

OBJECTIVE

Turn the current React Flow canvas into a complete workflow builder similar to Zapier / n8n.

Users must be able to visually build workflows using nodes and connections.

---

NODE SIDEBAR

Add a left sidebar listing available nodes:

Start
AI Agent
Image Generator
Caption Generator
Publisher
Scheduler
Comment Listener
Auto Reply
End

Each node must be draggable into the canvas.

---

DRAG AND DROP

Users must be able to:

drag nodes from the sidebar
drop them on the canvas
connect nodes using edges

Use React Flow drag and connect features.

---

NODE SETTINGS PANEL

When a node is clicked, open a configuration panel on the right side.

Allow editing node settings such as:

name
instructions
AI model
platform
schedule time
reply rules

Store the configuration inside node.data.

---

WORKFLOW STATE

The frontend must maintain:

nodes
edges
workflow settings

The workflow must be serializable to JSON.

Example:

{
"nodes": [...],
"edges": [...]
}

---

SAVE WORKFLOW

Connect the editor to the backend API:

POST /autoposter/api/workflows
PUT /autoposter/api/workflows/<id>

Send nodes and edges as JSON.

---

LOAD WORKFLOW

When opening a workflow, load its nodes and edges from the API and render them in React Flow.

---

NODE TYPES

Implement custom node components for:

StartNode
AINode
ImageNode
CaptionNode
PublisherNode
SchedulerNode
CommentListenerNode
AutoReplyNode
EndNode

Each node must display an icon and label.

---

UI LAYOUT

Page layout:

Left Sidebar → node library
Center Canvas → React Flow editor
Right Panel → node configuration

Use Tailwind CSS for styling.

---

EXECUTION SUPPORT

Ensure that the JSON produced by the editor matches the structure expected by the backend workflow execution engine.

---

GOAL

After this step the user should be able to:

create workflows
drag nodes
connect nodes
configure nodes
save workflows
run workflows from the backend
