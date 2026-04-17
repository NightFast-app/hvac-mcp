# Launch posts — drafts

These are value-first drafts per CLAUDE.md principle: "share the free tool,
don't sell." Each one is tuned to the target subreddit's culture. Edit the
voice if it doesn't sound like you before posting.

---

## r/HVAC — "I built a free tool that lets Claude/ChatGPT help you on service calls"

**Title:** I built a free HVAC tool that plugs into Claude and ChatGPT — PT charts, charge diagnosis, fault codes, code lookups

**Body:**

Been doing HVAC/plumbing in FL for 8 years (EPA 608 Universal). Got tired of
flipping between a PT chart app, a fault code PDF, and Googling IRC sections
on my phone between calls. So I built something that does all of it in one
place — inside whatever chat app you already use.

It's a Model Context Protocol server (the thing that lets Claude/ChatGPT use
your own tools). You install it once, and then in Claude on your phone you
can just ask things like:

- "R-410A at 118 psig, suction line is 50°F — what's my superheat?"
- "Carrier code 33, what am I looking for?"
- "Can I run a dryer vent 40 ft with two 90s?"
- "What's the IPC say about condensate traps?"

All 7 tools are free and open source (MIT). Covers:
- PT saturation for R-410A, R-32, R-454B, R-22, R-134a (with glide for blends)
- Superheat/subcool with TXV and piston diagnosis
- Symptom tree seeded by actual field experience (yes, float switch is top
  probable cause for "no cool" — I got chewed out by Claude early on when I
  left it out)
- Fault codes for Carrier, Trane, Goodman, Lennox, Rheem, York, Mitsubishi,
  Daikin (including alias handling — Bryant → Carrier etc.)
- IRC/IMC/IPC + Florida amendments (HVHZ, FL condensate specifics)
- Pipe sizing (DWV + supply, PEX bump)
- Duct sizing (ASHRAE friction chart)

**Github:** https://github.com/NightFast-app/hvac-mcp

Setup is one line in a config file. Directions are in
[docs/CONNECTING.md](https://github.com/NightFast-app/hvac-mcp/blob/main/docs/CONNECTING.md)
for Claude Desktop, Claude Code, the Claude mobile app, ChatGPT custom
connectors, and Cursor.

If you try it and hit something wrong in the data or the diagnosis tree,
please open an issue or reply here. I'd rather fix bad data than have it sit
there misleading someone else.

---

## r/mcp — "First vertical MCP for a real trade"

**Title:** hvac-mcp — a Model Context Protocol server for HVAC and plumbing
technicians

**Body:**

Most MCP servers I see are for devs (databases, Git, cloud APIs). Wanted to
try a vertical MCP for a non-tech trade to see how the interface translates.

Built **hvac-mcp** — 7 tools exposing field-service knowledge that an HVAC
tech actually reaches for on a call:

| Tool | Purpose |
|---|---|
| `hvac_refrigerant_pt_lookup` | Saturation PT for 5 refrigerants, bubble+dew for zeotropes |
| `hvac_refrigerant_charge_check` | Superheat/subcool → diagnosis (TXV/piston, restriction) |
| `hvac_diagnostic_symptom_tree` | Ranked probable causes with test + fix |
| `hvac_fault_code_lookup` | 8 brands, alias-aware (Bryant → Carrier, Ruud → Rheem) |
| `hvac_code_lookup` | IRC/IMC/IPC + state amendments, AHJ disclaimer hard-coded |
| `hvac_pipe_size` | DWV + supply, with invalid-combo rejection at the input layer |
| `hvac_duct_size` | Friction-rate method + Huebscher round-to-rect |

Notes from building it:
- Pydantic `model_validator` at the input layer is a great place to enforce
  domain rules (e.g. PEX is rejected for DWV before the tool ever runs).
- Zeotropic refrigerant blends forced me to return both bubble and dew points
  — a single saturation number would have been wrong on R-454B by ~2-3°F and
  misled a tech into thinking a unit was overcharged.
- The FastMCP `streamable-http` transport config is on `mcp.settings.*`, not
  kwargs to `.run()`. Lost an hour on that.

Free, MIT, runs via stdio or HTTP. https://github.com/NightFast-app/hvac-mcp

---

## r/ClaudeAI — "Example: using Claude on your phone to help with real service work"

**Title:** Built a custom MCP so Claude can answer HVAC diagnostic questions
on job sites

**Body:**

Realized the Claude mobile app supports hosted MCP connectors, so I built a
vertical MCP for my trade (HVAC/plumbing). It turns Claude into a pocket
reference that actually *runs the calc* instead of guessing.

Example exchanges from the last week:

> Me: "R-410A at 118 psig suction, line temp 50°F, liquid at 380 psig and
> 105°F. TXV system. What do I have?"
>
> Claude (with hvac-mcp): *calls hvac_refrigerant_charge_check* →
> Superheat 10.0°F, subcool 10.0°F, TXV in-spec. Charge looks correct.

> Me: "Dryer vent 40 ft with two 90s — will that pass inspection?"
>
> Claude (with hvac-mcp): *calls hvac_code_lookup* → IRC M1502 caps total
> equivalent length at 35 ft; deduct ~5 ft per 90. You're at 50 ft EL — over
> limit. Needs a booster fan or re-route.

The key insight: LLMs are really good at interpreting the messy way we
describe problems, but they're unreliable at calc math and code citations.
MCP lets you put the math and citations behind a tool call — so Claude never
makes up a pressure or an IRC section.

Github (MIT): https://github.com/NightFast-app/hvac-mcp
Config for the phone app is in docs/CONNECTING.md.

---

## FieldPulse / ServiceTitan / Jobber Facebook groups

**Short version (value-first, not a pitch):**

For anyone using ChatGPT or Claude on their phone during service calls —
a buddy built this free tool that gives the chatbot actual PT charts, fault
code lookups, and code citations so it stops making stuff up.

Takes about 2 minutes to set up:
https://github.com/NightFast-app/hvac-mcp

Not selling anything. Hosted version is $29/mo if you don't want to run it
yourself but the whole thing is open source either way.
