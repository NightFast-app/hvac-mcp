# Tool Catalog

Every tool in `hvac-mcp`, with inputs, outputs, and example calls.

All tool names are prefixed `hvac_` to avoid client-side name collisions with other MCP servers.

---

## Free tier

### `hvac_refrigerant_pt_lookup`

Saturation pressure/temperature lookup for common refrigerants.

**Inputs**
- `refrigerant` — one of `R-410A`, `R-32`, `R-454B`, `R-22`, `R-134a`
- `pressure_psig` *(optional)* — gauge pressure, psig
- `temp_f` *(optional)* — saturation temperature, °F

Provide exactly one of `pressure_psig` or `temp_f`.

**Returns**
```json
{
  "refrigerant": "R-410A",
  "pressure_psig": 118.5,
  "temp_f": 40.0,
  "glide_note": "",
  "source": "bundled PT tables"
}
```

For zeotropic blends (R-454B) the response distinguishes bubble point (use for subcool) from dew point (use for superheat).

---

### `hvac_refrigerant_charge_check`

Calculate superheat and subcool, then diagnose the charge state.

**Inputs**
- `refrigerant`
- `suction_pressure_psig`, `suction_line_temp_f`
- `liquid_pressure_psig`, `liquid_line_temp_f`
- `metering` — `TXV` (default) or `piston`

**Returns**
```json
{
  "superheat_f": 10.0,
  "subcool_f": 10.4,
  "diagnosis": "in_spec",
  "recommendation": "Charge is within TXV subcool target (8-12°F)."
}
```

`diagnosis` is one of: `in_spec`, `undercharged`, `overcharged`, `restriction_suspected`, `insufficient_data`.

---

### `hvac_diagnostic_symptom_tree`

Probable-cause ranking for a reported symptom.

**Inputs**
- `system_type` — `split_ac` | `heat_pump` | `furnace` | `mini_split` | `package_unit`
- `symptom` — free text, e.g. `"no cool"`, `"ice on suction line"`, `"short cycling"`

**Returns**
Ranked list of probable causes with test procedure and typical fix for each.

---

### `hvac_fault_code_lookup`

Decode OEM fault codes.

**Inputs**
- `brand` — Carrier / Trane / Goodman / Lennox / Rheem / York / Mitsubishi / Daikin
- `code` — the code as displayed (e.g. `"14"`, `"E3"`, `"P4"`)

**Returns**
Code meaning, probable causes, recommended first test, and a citation to the source service manual.

---

### `hvac_code_lookup`

IRC/IMC/IPC citations with jurisdiction-specific amendments.

**Inputs**
- `topic` — free text (e.g. `"water heater clearances"`, `"DWV venting"`)
- `jurisdiction` — two-letter state code (default `FL`) or `national`

**Returns**
Relevant code sections with excerpts, source citations, and a mandatory "verify with AHJ" disclaimer. This tool is informational — it does not represent legal authority.

---

### `hvac_pipe_size`

Plumbing pipe sizing.

**Inputs**
- `fixture_units` — DFU for DWV, WSFU for supply
- `material` — PVC / CPVC / copper / PEX / cast_iron
- `application` — `DWV` or `supply`

**Returns**
Minimum pipe size with IPC Table 709.1 reference (DWV) or Hunter's curve (supply).

---

### `hvac_duct_size`

HVAC duct sizing by friction-rate method.

**Inputs**
- `cfm` — required airflow
- `friction_rate` — inches water column per 100 ft (default 0.08)
- `duct_shape` — `round` or `rectangular`

**Returns**
Equivalent round diameter plus two to three rectangular options, with calculated velocity (FPM).

---

## Premium tier

All premium tools require a valid `HVAC_MCP_LICENSE_KEY`. Without one, they return a structured error pointing to the purchase URL.

### `hvac_invoice_draft`

Generate a formatted invoice from line items.

**Inputs**
- `customer_name`, `customer_address` *(optional)*
- `job_description`
- `line_items` — array of `{description, quantity, unit_price}`
- `tax_rate_pct` — default 6.5 (Florida)
- `notes` *(optional)*

**Returns**
Formatted markdown invoice plus subtotal, tax, and total.

### `hvac_estimate_from_symptom` *(planned)*
Combines diagnostic + local labor rate + parts DB into a customer-ready estimate.

### `hvac_parts_crossref` *(planned)*
OEM part → aftermarket equivalents with pricing from SupplyHouse and Grainger.

### `hvac_permit_lookup_fl` *(planned)*
Florida county permit system lookup. Lee, Collier, Charlotte first.
