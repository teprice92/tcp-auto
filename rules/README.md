# Jurisdiction Rules

Traffic control rules stored as data, layered by jurisdiction (see `docs/PLAN.md` §3.6). Where each
rule came from is listed in [`sources/README.md`](sources/README.md). The research behind them is in
[`docs/jurisdiction-research.md`](../docs/jurisdiction-research.md).

## Layout

```
federal/mutcd-11.yaml        FHWA MUTCD 11th Edition baseline
states/AZ.yaml               Arizona Supplement to the MUTCD (all roads in AZ)
states/AZ-adot.yaml          ADOT TTC Design Guidelines (state highways; also used as a practice reference)
cities/AZ/<city>.yaml        City/town rules
counties/AZ/<county>.yaml    Unincorporated county roads
```

## File format

```yaml
jurisdiction:
  id: AZ/tempe                  # unique id
  level: city                   # federal | state | state-agency | county | city
  name: City of Tempe
  extends: [states/AZ, cities/AZ/phoenix]   # loaded first, in order; this file overrides them
  applies_to: { road_owner: city }          # when this layer applies
status: partial                 # complete | partial | stub; how much of the jurisdiction is encoded
rules:
  <rule_key>:
    value: ...                  # the rule (shape depends on the key)
    cite: { source: <source id>, section: "4.2" }
    verified: true              # false = from a web summary or user report, not read from the document
    note: "..."                 # optional
```

For list rules (e.g., `police_required`), each item carries its own `cite` and `verified`.

**Merging:** a more specific layer replaces a rule with the same key. For safety minimums the engine
keeps the **strictest** value (longest taper or buffer, shortest device spacing). Police triggers and
required devices are **combined** across layers, never replaced.

**Unverified rules** (`verified: false`) are still applied when they make the plan safer (e.g., adding
a police officer). The report then labels them "confirm with agency".

## Common rule keys

| Key | Meaning |
|---|---|
| `peak_hours` | Weekday windows when restrictions are not allowed, by road class |
| `police_required` | List of triggers (`when:` conditions), each with a citation |
| `police_request_lead_time` | Notice needed to book off-duty officers |
| `work_hours` | Allowed construction hours (noise/night rules) |
| `night_work` | Definition of night and its requirements |
| `required_devices` | Devices required under given conditions (arrow boards, lights, signs) |
| `device_spacing` | Channelizing device spacing rules |
| `tcp_submittal` | Lead time, method, required contents, preparer qualifications |
| `road_closure` | Full-closure process and requirements |
| `pedestrian` | Pedestrian and transit accommodation |
| `school_zone` | School-zone handling in work zones |
