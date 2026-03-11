You are a senior frontend engineer.

Redesign the "Create Post" page for a social media autoposter dashboard.
The UI must be modern, clean, and optimized for Arabic (RTL layout).

Tech stack:

* HTML
* CSS
* Vanilla JavaScript
* Responsive design
* Dark theme UI
* Glass / modern dashboard style

Page layout must contain 3 main sections:

1. RIGHT SIDEBAR (Pages Panel)

* Fixed width: 300px
* Scrollable
* Shows all connected social pages
* Each page item contains:

  * Page logo
  * Page name
  * Platform icon (Facebook / Instagram / TikTok)
  * Toggle checkbox to enable posting
* Selected pages should be highlighted
* Add search input at top to filter pages

2. CENTER EDITOR (Post Composer)

* Main writing area
* Large textarea for post content
* Character counter (e.g., 0 / 5000)
* Media uploader supporting drag & drop
* Support image/video preview before publishing
* Post type selector:

  * Post
  * Story
  * Reel
* Schedule selector (date + time)
* Buttons:

  * Publish Now
  * Schedule
  * Save Draft

3. BOTTOM PREVIEW (Live Preview)

* Live rendering of how the post will appear
* Show preview card similar to Facebook post
* Include:

  * Page logo
  * Page name
  * Post text
  * Uploaded media preview
* Update automatically when user types

Design requirements:

* Use CSS Grid layout
* Sidebar on the right side (RTL layout)
* Center editor takes remaining width
* Preview panel fixed at bottom
* Smooth transitions and hover states
* Rounded cards
* Soft shadows
* Dark gradient background

CSS design style:

* Dark navy background
* Blue accent color
* Glass card style
* Rounded corners (12px)
* Subtle border highlights

JS functionality:

* Live preview updates while typing
* Drag & drop media upload
* Display uploaded image/video preview
* Toggle page selection
* Character counter update

Responsive behavior:

* On small screens:

  * Sidebar collapses
  * Editor becomes full width
  * Preview becomes accordion

Output must include:

1. Full HTML structure
2. Complete CSS styling
3. JavaScript interactions
4. Clean component structure
5. Comments explaining sections

Goal:
Create a professional autoposter interface similar to tools like Buffer, Hootsuite, or Meta Business Suite.
