Build a full **AI Agent page** inside my project called **AutoPoster**.

The page must implement a **Visual AI Automation Builder** where users can create automated workflows for social media using drag-and-drop nodes.

The system must be production-ready, modular, and designed for future expansion.

---

MAIN FEATURE

Create a page called:

/ai-agent

Inside the AutoPoster dashboard.

This page must allow users to visually build AI automations.

---

VISUAL WORKFLOW BUILDER

Implement a drag-and-drop workflow builder similar to:

* Zapier
* n8n
* Langflow
* OpenAI Agent Builder

Users must be able to:

* drag nodes
* connect nodes
* configure nodes
* execute workflows

Use a **node based interface**.

Each node represents an action.

---

CORE NODES

Start Node

AI Agent Node
Uses OpenAI to generate content.

Image Generator Node
Generates images from prompts.

Caption Generator Node
Creates captions and hashtags.

Publisher Node
Publishes to social platforms.

Scheduler Node
Schedules posts.

Comment Listener Node
Fetches comments.

Auto Reply Node
Uses AI to reply to comments.

End Node

---

NODE CONFIGURATION PANEL

When a node is clicked open a side panel.

Allow users to configure:

name
instructions
model
inputs
outputs

Example instructions:

"You are a marketing AI that generates engaging social media content."

---

WORKFLOW EXECUTION ENGINE

Create a backend system that reads the workflow.

Workflow must be stored as JSON.

Example structure:

nodes
edges
settings

The engine must execute nodes in sequence based on connections.

---

AI INTEGRATION

Use OpenAI models to power:

content generation
caption writing
comment replies
decision making

---

IMAGE GENERATION

Integrate an image generator API.

The agent must be able to send prompts and receive images.

---

SOCIAL MEDIA PUBLISHING

Create service modules for:

Instagram
Facebook
TikTok

The workflow should pass content to the publisher node.

---

COMMENT AUTO REPLY

The system must monitor comments.

When a new comment arrives:

send comment to AI
generate reply
publish reply

---

DATABASE STRUCTURE

Create tables for:

agents
workflows
nodes
executions
comments

---

SYSTEM ARCHITECTURE

Frontend
React
React Flow for node editor
Tailwind UI

Backend
Python Flask or FastAPI

Workflow Engine
Executes nodes

Queue System
Redis or Celery

Database
PostgreSQL

---

FILE STRUCTURE

autoposter
│
├ ai_agent
│
├ workflow_builder
│
├ nodes
│
├ engine
│
├ services
│
└ api

---

EXTRA FEATURES

Workflow testing mode
Execution logs
Node error handling
Workflow templates

---

DESIGN

Modern dark dashboard UI.

Left sidebar with node tools.

Center canvas for workflow.

Right panel for node settings.

---

FINAL RESULT

A complete AI automation builder where users can create AI agents that:

generate content
create images
publish posts
reply to comments
run automatically
