Extend the AI Agent Workflow Builder with **Knowledge Base nodes** that allow the system to store and retrieve product and pricing information.

The goal is to allow the AI Agent to answer questions using real business data such as products, prices, and specifications.

---

NEW NODE TYPES

knowledge_upload
knowledge_search

---

1. KNOWLEDGE UPLOAD NODE

type: "knowledge_upload"

Purpose:
Upload product information, price lists, or specifications into the system knowledge base.

Frontend settings:

Upload type:

file
manual_entry

Fields:

Product name
Price
Description
Specifications

Allow uploading:

CSV
Excel
JSON

Example JSON node:

{
"type": "knowledge_upload",
"data": {
"source": "file",
"file_type": "csv"
}
}

Backend behavior:

Store product data in database table:

products

Structure:

id
name
price
description
specifications

---

2. KNOWLEDGE SEARCH NODE

type: "knowledge_search"

Purpose:
Search products and prices using user questions.

Frontend settings:

Search source:

products
pricing
specifications

Query variable:

{{message_text}}

Example JSON:

{
"type": "knowledge_search",
"data": {
"query": "{{message_text}}"
}
}

Backend function:

def run_knowledge_search(node, context):

```
query = context.get("message_text")

results = search_products(query)

context["knowledge_results"] = results
```

---

3. AI AGENT INTEGRATION

The AI Agent node must receive product data from the context.

Example prompt:

Use the following product information to answer the user:

{{knowledge_results}}

User question:

{{message_text}}

---

WORKFLOW EXAMPLE

WhatsApp automation:

whatsapp_listener
↓
knowledge_search
↓
AI Agent
↓
whatsapp_send

---

RESULT

The AI agent will be able to answer customer questions using real data about products, prices, and specifications stored in the system.
