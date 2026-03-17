@codebase

Find where Facebook publishing payload is created.

Ensure the visibility field is mapped correctly.

If visibility == "public"
    published = True

If visibility == "hidden"
    published = False

Update all Facebook publishing calls:

POST /{page_id}/feed
POST /{page_id}/photos
POST /{page_id}/videos

Ensure payload always contains:
published: True or False

Show the exact code fix.