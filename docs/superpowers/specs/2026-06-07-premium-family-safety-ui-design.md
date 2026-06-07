# Premium Family Safety UI Design

## Goal

Redesign the frontend into a premium, family-safe product experience for The Nightwatchman. The interface should feel calm, mature, lively, and interactive without looking like a generic AI demo or a noisy security dashboard.

The primary headline is:

> A trusted voice beside every call.

The product should explain that The Nightwatchman protects families from scam calls through real-time monitoring, claim verification, calm coaching, trusted-contact alerts, and report generation.

## Visual Direction

Use the approved `Living Signal` direction.

The background should feel custom to the product: a soft field of moving call signals, verification nodes, and trusted-contact rings. It should look alive but composed. Motion should be slow, layered, and meaningful rather than decorative. The animation should avoid generic particle effects, glitch effects, cyberpunk neon, and fear-heavy scam imagery.

The design should blend:

- Premium family safety: warm, trusted, protective.
- Mature AI product: intelligent, real-time, capable.
- Calm healthcare/insurance polish: reassuring rather than alarmist.

## Theme System

Add light mode and dark mode.

Light mode should use warm ivory, mist blue, soft teal, sage, and deep slate text. It should feel bright, safe, and premium.

Dark mode should use deep navy, moonlit teal, muted blue, and glass surfaces. It should not use pure black or harsh neon. Dark mode should feel like quiet nighttime protection.

The theme toggle should:

- Respect the user's system preference on first load.
- Persist explicit user choice in `localStorage`.
- Update the page with smooth, restrained transitions.

## Landing Page Structure

The page should be reorganized into a full product landing page with the live monitoring console integrated below the product story.

Recommended sections:

1. Navigation
   - Brand: The Nightwatchman.
   - Anchors for Product, Agents, Live Console, and Trust.
   - Theme toggle.

2. Hero
   - Headline: `A trusted voice beside every call.`
   - Supporting copy explaining that the product listens for scam tactics, verifies suspicious claims, coaches safer responses, and can alert a trusted contact.
   - Primary CTA: `Start live monitoring`.
   - Secondary CTA: jump to how it works or view agents.
   - Compact status card showing connection state, current risk, and system readiness.

3. Product Promise Cards
   - Real-time scam tactic detection.
   - Claim verification for suspicious statements.
   - Calm coaching prompts during risky calls.
   - Trusted-contact alerts when help is needed.

4. Multi-Agent Constellation
   - Show the product as a coordinated safety team.
   - Agents should appear as interactive nodes connected by subtle signal paths.
   - Hover/focus states should reveal each agent's role.
   - The section should feel lively and premium, not gimmicky.

5. How Protection Works
   - A simple three-step flow:
     1. Listen for risk patterns.
     2. Verify and coach in real time.
     3. Alert family or generate a report when needed.

6. Live Monitoring Console
   - Preserve existing WebSocket/API behavior.
   - Redesign current panels into premium glass cards.
   - Keep start/end call actions, risk gauge, transcript, verification tags, coaching tips, ally alerts, and call outcome banners.

7. Trust and Privacy
   - Explain the privacy posture in plain language.
   - Emphasize calm assistance and family safety.
   - Note that clean conversations can be deleted and reports are generated only when needed, matching current app behavior.

## Agent Presentation

The UI should make the current agent system visible as a strength.

Agents to show:

- `Sentinel`: watches the call for scam tactics and risk escalation.
- `Verifier`: checks suspicious claims and marks unverifiable statements.
- `Ally`: prepares trusted-contact alerts when the caller may need outside help.
- `Coach`: suggests calm, safe things to say during the call.
- `Scribe`: captures only the useful incident details needed for reports and review.

Each agent node should include a concise description, an active/inactive visual state, and a mature hover/focus interaction. The system should read as a coordinated protection layer, not as a novelty chatbot swarm.

## Live Background Behavior

The `Living Signal` background should adapt to product state:

- Idle: slow teal and mist-blue motion with broad, calm rings.
- Connected: slightly brighter signal paths and active agent nodes.
- Elevated risk: warmer amber accents and tighter rings.
- High risk: restrained red accents, stronger warning card, no frantic flashing.

The implementation should support `prefers-reduced-motion` by disabling continuous animation and keeping static layered gradients or very subtle transitions.

## Existing Behavior To Preserve

The redesign must preserve:

- WebSocket connection to `ws://localhost:8000/ws`.
- `POST /reset-call` start behavior.
- `POST /end-call` end behavior.
- Report download link for scam outcomes.
- Known scammer, clean call, error, coaching, ally alert, transcript, risk gauge, playbook match, and verification result displays.

No backend API changes are required for this UI pass.

## Testing And Verification

Because this frontend currently has no test setup, implementation should at minimum verify:

- `npm run build` succeeds.
- Theme selection persists after reload.
- Theme initializes from system preference when no saved choice exists.
- Start/end monitoring buttons still call the existing endpoints.
- WebSocket events still update transcript, risk, verification, coaching, and ally alert UI.
- Reduced-motion mode does not rely on continuous animation.
- Layout remains usable on mobile, tablet, and desktop.

If a test framework is added, tests should focus on theme initialization/persistence and pure helper behavior rather than trying to snapshot the entire visual page.

## Scope

In scope:

- `frontend/src/main.jsx`
- `frontend/src/styles.css`
- `frontend/index.html` metadata if needed

Out of scope:

- Backend changes.
- New external UI or animation dependencies.
- Authentication or user accounts.
- Production marketing copy beyond the landing page text needed for this app.
