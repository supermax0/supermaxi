You are a senior UI/UX designer and front-end architect.

Redesign the entire Publisher SPA interface of a Flask web application called "Finora Publisher".

The goal is to create a modern, professional social media publishing dashboard similar to:

Meta Business Suite
Buffer
Hootsuite
Notion style dashboards

The system currently contains these pages:

1) Dashboard
2) Create Post
3) Media Library
4) Settings

The redesign must keep all backend endpoints unchanged but completely upgrade the UI and UX.

--------------------------------

GENERAL DESIGN REQUIREMENTS

Create a premium SaaS-level interface.

Style inspiration:

• Linear.app
• Vercel dashboard
• Notion
• Meta Business Suite

Use:

Dark theme first design
Soft glassmorphism cards
Subtle gradients
Smooth micro-animations
Clean typography

Primary colors:

Background:
#0b1020

Card:
rgba(255,255,255,0.04)

Accent gradient:
#6366f1 → #8b5cf6

Success:
#10b981

Error:
#ef4444

Border:
rgba(255,255,255,0.08)

--------------------------------

LAYOUT STRUCTURE

Use a modern responsive layout:

Desktop:
Sidebar (left)
Main content
Optional right preview panel

Mobile:
Collapsible sidebar
Single column layout
Floating action buttons

Use CSS grid + flexbox.

Breakpoints:

Mobile < 640px
Tablet < 1024px
Desktop ≥ 1024px

--------------------------------

SIDEBAR DESIGN

Create a premium vertical sidebar with:

Publisher logo
Navigation items

• Dashboard
• Create Post
• Media Library
• Settings

Icons:

Use Lucide icons.

Active item style:

background gradient
rounded corners
soft glow effect

Add subtle hover animations.

--------------------------------

DASHBOARD PAGE

Design a professional analytics dashboard.

Top section:
4 stat cards

Total posts
Published
Scheduled
Failed

Each card should include:

Icon
Number
Label
Gradient top border

Below that:

Recent Posts Table

Columns:

Content preview
Status
Pages count
Date
Actions

Status badges:

Published → green
Scheduled → blue
Failed → red
Draft → gray

--------------------------------

CREATE POST PAGE

Create a modern 3-panel layout.

LEFT PANEL

Post editor.

Components:

Large textarea
AI assistant tools

Buttons:

Generate text
Rewrite
Generate hashtags

Dropdowns:

Tone
Length
Content style

--------------------------------

RIGHT PANEL

Live Facebook preview.

Show:

Page avatar
Page name
Post content
Attached media preview

Preview must update live as the user types.

--------------------------------

BOTTOM SECTION

Page selection area.

Show connected pages as rounded tags.

Allow multi-select.

--------------------------------

MEDIA ATTACHMENT

Allow:

Image preview cards
Video preview cards
Drag & drop upload
Media library picker

Media cards must include:

Thumbnail
File name
Delete button

--------------------------------

MEDIA LIBRARY PAGE

Create a clean media manager.

Top toolbar:

Search
Filter:

All
Images
Videos

Upload button

--------------------------------

MEDIA GRID

Responsive grid:

Desktop: 5 columns
Tablet: 3 columns
Mobile: 2 columns

Each media card:

Thumbnail
File name
Size
Delete icon

Add hover overlay:

Preview
Use in post

--------------------------------

SETTINGS PAGE

Divide into sections:

Facebook App Credentials

App ID
App Secret

User Token

Pages list

Each page card must show:

Page name
Page ID
Remove button

--------------------------------

MICRO INTERACTIONS

Add subtle animations:

Hover lift on cards
Sidebar hover glow
Button ripple effect
Smooth transitions (200ms)

--------------------------------

TECH STACK

Write clean production ready code using:

HTML
CSS
Vanilla JavaScript

Do not use heavy frameworks.

Use:

CSS variables
Reusable components
Responsive design
Accessible UI

--------------------------------

OUTPUT REQUIRED

Generate:

1) publisher.css (modern design system)
2) publisher_layout.html
3) dashboard.html redesign
4) create_post.html redesign
5) media_library.html redesign
6) settings.html redesign
7) minimal JS for UI interactions

Ensure everything works inside Flask templates.

--------------------------------

IMPORTANT

Do not modify Flask routes or backend logic.

Only upgrade the UI layer.

Ensure the design works perfectly on:

Desktop
Tablet
Mobile