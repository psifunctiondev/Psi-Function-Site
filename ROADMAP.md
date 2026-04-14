# Psi Function Website — Roadmap

Captured 2026-04-03 from Quinn's vision session.

---

## 1. /home — Prospect Chat Agent
**Ambition: High | Priority: TBD**

An embedded chat widget on the home page wired to a specialized agent on the backend. The agent helps prospective clients brainstorm how Psi Function could help their business — engaging, adding immediate value, whetting appetites, and generating leads all at once.

**Considerations:**
- Security (input sanitization, rate limiting, session isolation)
- Gracefully handling trolls / off-topic abuse
- Agent persona and knowledge base (services, pricing boundaries, case studies)
- Lead capture (optional email/name collection, conversation summaries to CRM)
- Cost management (token usage per conversation)

**Existing scaffolding:** `chat-widget.js`, `graph-view.js` already in the static JS — may have early plumbing.

---

## 2. /services — Interactive Knowledge Graph
**Ambition: High | Priority: TBD**

Below the current services card grid, an Obsidian-style graph view showing interconnected nodes:
- **Business functions:** Marketing, Sales, Customer Service, Finance, Operations, HR, etc.
- **Modern technologies:** Generative AI, Cloud Computing, RPA, Data Analytics, etc.

Each node has a synopsis description. Edges connect related concepts (e.g., "Generative AI" ↔ "Marketing", "Cloud Computing" ↔ "Operations"). Clicking a node reveals its description and connections.

**Purpose:** Show non-technical business owners how tech buzzwords map to their actual business concerns, and demonstrate that Psi Function spans both worlds.

**Existing scaffolding:** `graph-view.js` in static JS — early mount point already in `main.js`.

---

## 3. /zeitgeist — Curated News & Thought Capital (NEW PAGE)
**Ambition: Medium-High | Priority: TBD**

A new page aggregating news articles and thought pieces about small business, technology, and their intersection. Doxa maintains a curated database in the background by scanning the web for relevant content.

**Features:**
- Articles tagged by: business function, industry segment, technology
- Amazon-style faceted filters — toggle tags on/off to narrow results
- Each article: title, source, date, summary, tags, link
- Regularly updated (agent-curated, possibly daily)

**Purpose:** Demonstrate expertise, provide immediate value to visitors, drive repeat traffic.

**Backend needs:** Article database (PostgreSQL?), tagging system, curation agent/cron, API endpoints for filtered queries.

---

## 4. /portal — Client Portal (EXPAND EXISTING)
**Ambition: Medium | Priority: Could start now**

Authenticated client-specific sitelets accessible via direct URL or hidden login. Each client gets a personalized space containing:

- Proposals and SOWs
- User story backlogs (pulled from OpenProject)
- Static assets (user guides, documentation)
- Custom UI front-ends (per-client tools)
- Invoice history

**Existing scaffolding:** Auth blueprint (`/auth`), portal blueprint (`/portal`), user model, login template, Flask-Login already wired up.

**Next steps:** Design the per-client dashboard layout, decide on OpenProject API integration approach, set up file storage for static assets.

---

## Quick Wins (in progress)
- [x] Site footer (PR #11, merged & deployed)
- [ ] Page intro text blocks for Services & About (PR #12, placeholder copy)

## Infrastructure Notes
- Flask app with Jinja2 templates, Vite for JS bundling
- Three theme modes: day, twilight, night (auto by time of day)
- 5-column responsive grid system
- Deployed to production at psifunction.com
- Auth/portal/admin blueprints already scaffolded
