# FINORA product landing page

The public landing template now presents the product with real UI captures, a keyboard-accessible
five-screen tour, Windows download, setup steps, operational features, subscription plans and FAQs.
It keeps the existing Flask routes, registration URLs, pricing data, SEO metadata and chat widget.

## Files

- `templates/landing_dynamic.html`: document metadata and existing CMS context.
- `templates/landing/_product_page.html`: new page structure, default product copy and screenshots.
- `static/css/landing_product.css`: responsive visual design; the legacy CSS remains for the chat widget.
- `static/js/landing_product.js`: mobile navigation, RTL tabs, image dialog and focus restoration.
- `utils/landing_release.py`: installer availability and metadata.
- `static/images/landing/README.md`: screenshot provenance.

## Content editing

Existing features, modules, pricing, FAQs, SEO, header CTAs and custom hero text remain data-driven.
The old seeded hero title/description receive the new product presentation; custom hero text is retained.
The fixed illustrative performance statistics and unverified seeded testimonials are not displayed.
Testimonials can be displayed after verification by setting the testimonials section's content to
`{"verified": true}`. Do not set this for seeded/example quotes.

Optional sections can be added using the existing landing CMS section editor (no schema migration):

- `product_tour`: title, description, visibility, and `content.items`, a list of objects with `label`,
  `title`, `description`, `image_url`, and `platform`. Defaults to the five real captures.
- `desktop`: title, description and visibility. An optional `button_primary_url` and
  `button_primary_text` can select a hosted installer. For a custom URL, optional
  `content.release_label` supplies the release description; bundled version metadata is not shown.
- `hero.content.intro`: optional override for the short introduction. `hero.image_url` can replace
  the primary screenshot. Legacy logo/image placeholders fall back to a real app capture.

Hidden sections retain only an `is_visible: false` marker in the public section map so template
defaults cannot accidentally redisplay them. Their hidden copy is not returned publicly.

## Installer delivery

The local public download folder contains the existing Windows 10/11 x64 installer, version 0.7.1.
Its source is `desktop/finora_management/release/win10-11/` and its size is 115,781,994 bytes.
SHA-256: `2253c15ac6f70d9ac9d94fb7b23802bc4bf1dbe2e28704cb336dac18a540b824`.
This task verifies delivery and file integrity; it does not rebuild or install the desktop application.

Executable installers are excluded from Git because this artifact exceeds GitHub's file-size limit.
Deploy the installer separately into `static/downloads/`, alongside the tracked
`static/downloads/finora-management.json` manifest. Updating a release means shipping the new file
and updating the manifest together. The download button is only shown when the local file exists
and matches the manifest size; it falls back to an inquiry link when unavailable. Custom CMS download
URLs are administrator-managed and must be checked when changed.

Deploy the templates, CSS, JS, screenshots, local fonts, manifest and Python changes together, then
restart the application to load the Python changes. No production publish or server restart is part
of this local redesign. Prices shown are the existing CMS prices, not new pricing decisions.

## Verification

`py -3.11 -m pytest tests/test_landing_product.py -q` checks template defaults, hidden content,
custom CMS copy, signup behavior, unverified testimonials and safe installer availability.

`output/landing-redesign/check.mjs` verifies the page in Chrome at 1920, 1440, 1024, 768, 390 and
360 pixels, tests gallery controls and RTL keyboard navigation, image-dialog focus restoration,
FAQ expansion, mobile navigation, reduced motion, JS errors and installer HEAD/size.
The read-only preview server in that directory renders a captured public CMS payload on port 5016,
without importing the main application or touching business databases.
