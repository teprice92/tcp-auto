# TCP-Auto

Draft **Traffic Control Plans (TCPs)** from electrical/utility design plans.

TCP-Auto will read PDF design plans in which grid devices are marked for installation or
removal, find the work location on the road, and lay out a draft TCP (signs, tapers,
channelizing devices, buffers, flaggers, police positions, and reduced-speed zones). The
layout follows the federal MUTCD baseline plus state and county/city rules, with a minimum
work area of 250 ft. Engineers then refine the draft in a drag-and-drop editor.

The TCP is a standalone deliverable, not drawn onto the design plans. It is generated on an
OpenStreetMap street map and exported as an emailable PDF report: a map highlighting the plan,
a brief plain-language explanation, and a timeline (with optional detail pages), ready to send to a
county or city for approval.

An LLM assistant is planned as an **optional, pluggable** helper (placeholder in v1) for
interpreting notes, resolving ambiguous symbols, and proposing the work-zone centerpoint.

> Generated plans are drafts. They must be reviewed and approved by qualified personnel
> before use.

See **[docs/PLAN.md](docs/PLAN.md)** for the full plan: architecture, pipeline, rules engine,
editor, LLM interface, roadmap, and open questions.

## Status

Planning phase. No code yet.

- **Area:** Arizona East Valley (Mesa, Chandler, Gilbert, Tempe, Queen Creek, Apache Junction,
  and unincorporated Maricopa/Pinal).
- **Users:** one shared tool for designers, engineers, inspectors, schedulers, and construction
  consultants at an electrical utility. No workflow or approval process built in.
- **Drawings:** v1 assumes work items are labeled "Construct" or "Remove" and sit next to roads.
- **Work types:** mid-block, intersections (including signalized), and night work. Police officers
  are added per each city's rules; school zones always require one.
- **Platform:** hosted web app in its own cloud account with invite-only sign-in, so the utility's IT
  isn't needed to start. Reports go out as email drafts that open in Outlook. Microsoft 365 single
  sign-on and Outlook/SharePoint integration are optional later.
