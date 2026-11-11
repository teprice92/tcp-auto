# Jurisdiction Research: East Valley Traffic Control Rules

What the source documents say about the topics TCP-Auto has to encode: police officers, restricted
hours, night work, intersections and signals, school zones, and TCP submittal. Document ids refer to
[`rules/sources/README.md`](../rules/sources/README.md). Machine-readable versions are in `rules/`.

> **Confidence:** items marked **[source]** were read directly from a provided document. Items marked
> **[web]** come only from web search summaries and must be checked against the actual document
> before they are relied on.

---

## Summary table

| Topic | Tempe | Gilbert | Mesa | Queen Creek | Chandler | Apache Jct. |
|---|---|---|---|---|---|---|
| Base manual | Phoenix TBM + MUTCD/AZ Supp, with Tempe changes **[source]** | MUTCD (Ord. #798) with Gilbert changes **[source]** | Mesa TTC Manual (own) **[web]** | MUTCD Part 6 as amended by AZ; MAG + QC supplement; Phoenix TBM referenced **[source/web]** | Chandler EDSM Ch. 7 **[web]** | Not found |
| Peak-hour ban (weekdays) | Arterial/collector: 7:00–8:30, 15:30–18:30 **[source]** | Arterial lane closures: 5:30–8:30, 15:30–19:00 **[source]** | Arterial/collector: 6:30–8:30, 16:00–18:00 **[web]** | Not found | Not found | Not found |
| Police officer triggers | "May be required"; city decides at review **[source]**. Via Phoenix TBM: one through lane at a signal **[web]** | **Within 300 ft of a signalized intersection**, or when the Traffic Engineer requires **[source]** | "May be required"; Mesa officers get priority **[web]** | Off-duty MCSO deputy when the accepted TCP says so **[web]** | Off-duty officers per §7.6.5.1 (text not seen) **[web]** | Not found |
| School zone → officer | Not in document | Not in document | Not in document (school crosswalks must stay open) **[web]** | Not in document | Not seen | Not seen |
| Night work | City Code §20-8 hours + written authorization letter **[source]** | "Nighttime" is an hours-of-operation option on the TCP application **[source]** | Not found | Not found | Not found | Not found |
| TCP lead time | 3 full working days **[source]** | 2 business days (48-hr review); road closure 20 days **[source]** | Not found | 10 working days; full closure 21 working days **[web/source]** | Not found | Not found |
| Who prepares the TCP | Barricade company with a Tempe annual certification; ATSSA-certified designers **[source]** | Certified ATSSA member **[source]** | Not found | Not found | Not found | Not found |

---

## Tempe — `tempe-tbm-2016` [source]

**Adopted standards (§4.2):** the most recently adopted **City of Phoenix Traffic Barricade Manual**,
the **MUTCD**, and the **ADOT Arizona Supplement**, with the Tempe changes below. *So for Tempe, the
rules engine has to load the Phoenix TBM rules first and then apply the Tempe overrides.*

**Restricted hours**
- Traffic restrictions are **not permitted on arterial/collector streets 7:00–8:30 a.m. and
  3:30–6:30 p.m. on weekdays** (§4.2). Exceptions only for emergencies or with approval from the
  City Traffic Engineer (§4.4).

**Police officers**
- "The contractor, utility or other agency, **may be required** to provide a uniformed off-duty
  police officer to assist with traffic control" (§4.2).
- The City may change "the use of off-duty police officers" when it reviews the plan (§4.4).
- Off-duty officer line: 480-350-8789 (§7). A Tempe PD page (web) says requests go through the
  Off-Duty Coordinator, need 72 hours' notice, and have a 3-hour minimum **[web]**.

**Night work / work hours (City Code §20-8, quoted in §4.3)**
- Any night-time work needs a **written authorization letter** from Neighborhood Services (480-350-8883).
- Allowed construction hours **in or within 500 ft of a residential zone**:
  - Apr 15–Oct 15: 6:00 a.m.–7:00 p.m.
  - Oct 16–Apr 14: 7:00 a.m.–7:00 p.m.
- Commercial/industrial zones **not** within 500 ft of residential: 5:00 a.m.–7:00 p.m.
- Saturdays, Sundays, holidays: 7:00 a.m.–7:00 p.m. (concrete pouring 6:00 a.m.–7:00 p.m.).
- Anything outside these hours needs written authorization.
- Goal: "Conduct night & weekend work in non-residential areas" (Executive Summary).
- Fee definition of night: **7:00 p.m.–6:00 a.m.** (§5.2).

**Required equipment**
- Short-term operations (≤ 60 min): an **operating arrow panel**, plus a light bar, yellow flashers,
  or strobe lights, plus a **cone taper of at least 50 ft** (§4.2).
- Bike lane closure: a **SHARE THE ROAD (W16-1P)** sign 50 ft before the merging taper, with more
  50 ft downstream of each intersecting collector/arterial (§4.6).
- A construction project sign (3'×5', orange) on major arterials/collectors for work lasting **> 1 week** (§4.7).
- Changeable message boards **48 hrs ahead** when all of these apply: ≥ 50% capacity reduction (per
  direction), > 5 days, and on an arterial right after a state route interchange. **7 days ahead** for a
  ≥ 66% reduction during peak hours (§4.7).
- Pavement drop-offs: ≤ 3" → vertical panels (and close the bike lane); 3–18" → 3 ft buffer;
  ≥ 18" → 10 ft buffer (§4.7).

**Pedestrians / transit (§4.6)**
- Pedestrian escort or delineated detour. Pedestrian detours in the roadway are protected with concrete or water-filled barriers.
- Keep transit stops accessible. Relocating a stop more than 500 ft away needs approval.

**TCP submittal (§4.3)** — **must be reflected in the TCP-Auto report for Tempe**
- At least **3 full working days** before work. Submit via Accela (epermits.tempe.gov) or in person.
- A right-of-way permit is required first, and its **permit number must appear on the TCP** (§3).
- Required contents: start/end dates; **hours of traffic restrictions**; ROW permit #; precon meeting
  date and inspector (if any); contractor name/contact/phone; **all streets labeled** in and around the work
  area; **work zone**; location of **all TTC devices**; potential conflicts (**bus stops, bike lanes,
  driveways**); **crosswalks and traffic islands**; **whether intersections are signalized**; **lane
  configurations at intersections** (protected lefts, free rights, shared lanes).
- Changes/extensions: by 11:00 a.m. the business day before expiration (2 days if transit is affected) (§4.5).
- Work longer than 60 days must be resubmitted (Exec. Summary, §5.2).

**Who places devices (§2, §2.2)**
- A barricade company holding a **Tempe annual traffic barricade certification**, with trained staff
  (IMSA/ATSSA) and **ATSSA certification for designers**, field supervisors, foremen and operations managers.

**Fees (§5)**
- $50 TCP review. **$12,000 annual traffic barricade fee for utilities** unless exempted.
- Variable fees on weekday arterial restrictions by capacity reduction and duration. These don't apply at
  night, on weekends, or on holidays. Arterial closures cost $2,500 per day per direction. Sidewalk and bike lane closures cost $50/day (max $1,000).

---

## Gilbert — `gilbert-te-app-2014` [source]

> This packet is dated **Aug 2014**. Ask Gilbert Traffic Engineering whether a newer version exists.

**Adopted standards:** MUTCD adopted by **Ordinance #798**. Ordinance §10-5(b) changes:
- **Arrowboards are required for all lane closures on arterial streets.**
- **Lane closures on arterial streets are not permitted 5:30–8:30 a.m. or 3:30–7:00 p.m.** unless
  approved by the Traffic Engineer.

**Police officers** (TCP Application page)
- "Extra duty Town of Gilbert police officers are **required whenever construction activity is occurring
  within 300 feet of a signalized intersection**, in right-of-way, Public Utility Easement or when
  required by the Traffic Engineer."
- Request **at least 5 business days** before the start date (Extra Duty Police Request Line 480-635-7194).
- The approval box includes "**Gilbert Police Officer Required**", so the reviewer can add the requirement.
- **Flagging:** "If flagging is to occur on any street, the contractor shall use **ATSSA certified flaggers
  or extra-duty Town of Gilbert Police Officers**."

**Hours of operation choices on the TCP application:** 24-hour, **Non-Peak 8:30am–3:30pm**, Nighttime, Other.

**Other requirements**
- The TCP must be **designed and submitted by a certified ATSSA member**, at least **2 business days** before
  the start (Ord. §10-5(b)(1)). Normal review is 48 hours; a Friday or holiday submittal starts review the next business day.
- An **ATSSA-certified Traffic Control Supervisor must be on-site** whenever devices are installed on an arterial street.
- A pre-construction meeting with Traffic Engineering is required after the permit is issued.
- Extensions: 2 business days' notice. Road closure extensions: 15 business days.
- Contractor must provide a 24-hour emergency contact and say who resets and maintains devices (AM/PM, after hours).
- Approved TCP and permit kept on-site.
- **Road closures:** request **20 days** ahead; info signs posted **10 days** ahead; a **14 ft emergency
  access lane** at all times; a fire access route plan; sign-offs from school district transportation
  directors (Gilbert PS, Chandler USD, Higley USD), private/charter schools, USPS, Parks, Fire Marshal,
  Police Chief, and Valley Metro.
- **Haul routes:** 8:30 a.m.–3:30 p.m., Mon–Fri only.

**Submittal:** traffic.workzones@gilbertaz.gov for amendments; Traffic Engineering 480-503-6186.

---

## Queen Creek — `qc-full-closure-2023`, `qc-dspm-notes-2007` [source]; `qc-tcp-app` [web]

**Standards:** encroachment work follows the **MAG Specifications and Details**, the **Queen Creek
Supplement to MAG**, and the **MUTCD** (Paving Note 4). A TCP for ROW work goes to Public Works for
review and approval (Paving Note 19). A ROW encroachment permit is required (Paving Note 5).

**TCP application [web]:** an approved encroachment permit is needed first. The TCP is due at least
**10 working days** before work, submitted as one combined PDF (application + signed permit + TCP).
Devices follow MUTCD Part 6 as amended by Arizona. An **off-duty Maricopa County Deputy Sheriff (Queen Creek
District)** is required whenever the accepted TCP says so. Haul TCPs are due 48 hours ahead. Copies of the TCP
and permit must be kept on site.

**Full roadway closure policy (2023) [source]**
- The Traffic Engineer approves closures of **up to 7 days**. Longer closures go to the Town Manager.
- Allowed only when other traffic control can't mitigate the hazard or the work requires it. Denied if a feasible alternative exists.
- Submit **21 working days** before the start (emergencies excepted).
- A **detour plan** is required. The applicant fabricates any custom signs.
- **Message boards 2 weeks** in advance. VMS should be used for real-time information.
- A bond may be required.

---

## Mesa — `mesa-ttcm-2ed` [web only]

- Mesa uses its **own Temporary Traffic Control Manual**, which replaced the Phoenix TBM plus Mesa Supplement on 1/11/2018.
  The **2nd Edition** is reported effective **July 2026**.
- Peak hours: **6:30–8:30 a.m. and 4:00–6:00 p.m., weekdays**. Restrictions on **arterial and collector**
  streets are generally not allowed during peak hours unless approved. Some arterials near freeways may
  have different peak hours.
- 1st Edition: on a multi-lane street, only **one lane in a single direction** may be restricted, and not during peak hours.
- **Police:** off-duty officers or flaggers "may be required." Mesa officers get priority. Off-duty
  officers or flaggers may act as **pedestrian spotters** but aren't required to.
- **School zones (2nd Ed. draft):** school zone signs must stay visible inside a work zone, and
  **"School zone crosswalks must remain open and accessible at all times."**

**Needed:** the final 2nd Edition PDF, to confirm all of the above and find the police/signal triggers.

---

## Chandler — `chandler-edsm`, `chandler-udm148` [web only]

- Traffic control falls under **EDSM Chapter 7 (Traffic Barricade Design)**. **§7.6.5.1 Police Officers**
  covers extra-duty officers (scheduled via OfficerTRAK). The requirement text itself wasn't seen.
- **UDM-148 Utility Permit Manual** (June 2024) has a traffic control plan section. Work outside the
  permitted time frame isn't allowed and is subject to sanctions under Chapter 7.

**Needed:** EDSM Ch. 7 and UDM-148. These are the most important missing documents for a utility.

---

## Apache Junction — `aj-code-row` [web only]

- A right-of-way encroachment permit is required for all work in the city ROW, with a 100% performance bond or equivalent.
- No TCP-specific requirements found yet.

---

## Phoenix Traffic Barricade Manual — `phx-tbm-9r` [web only]

Needed because **Tempe adopts it** and Queen Creek references it.
- When lane closures leave **one through lane** at a signalized intersection, the permittee must provide a
  **uniformed police officer to manually allocate green time**, unless otherwise approved.
- Construction near signalized intersections is allowed **only during off-peak hours**.

---

## Arizona statewide

### Arizona Supplement to the MUTCD, 11th Edition (Jan 2026) — `az-supp-mutcd11-2026` [source]
- **Arizona is on the MUTCD 11th Edition.** The supplement replaces specific sections. Anything it
  doesn't include stays as in the national MUTCD.
- **§6A.02 (AZ):**
  - Lane closures on high-volume streets should be scheduled off-peak.
  - **"Night work should be considered if the work can be accomplished with a series of short-term operations."**
  - Coordinate early with school officials about pick-up/drop-off, bus routing and safe routes to school.
  - Coordinate early with cross-street agencies and emergency services.
  - Paragraph 04 lists urban low-speed differences: shadow vehicles, truck-mounted attenuators, crash
    cushions and barriers are typically not needed, and extra signs beyond the MUTCD are typically not appropriate.
- **§6G.08 (AZ):** work zone speed limit (G20-5aP, R2-12) and higher fines signs (R2-10/R2-11).
  **Double-fine signs in *state highway* work zones (ARS §28-652, §28-710) are placed only when workers
  are present** and follow the ADOT TTC Design Guidelines figures.
- **Fig. 6P-44AZ:** replaces TA-44 (work near an entrance ramp). Freeway-only, so not a v1 concern.
- **Part 7 (AZ):** school signs, school speed limit zones (begin 200–500 ft ahead of school grounds or a
  crossing), and higher-fines school zones. Where an **Arizona School Crossing (ARS §28-797)** exists, signs follow the ADOT School Area Guidelines.

### ADOT Temporary Traffic Control Design Guidelines (Apr 2025) — `adot-ttcdg-2025` [source]
Written for the **state highway system** (including utility work on it). Many cities also follow its practices.
- **By state law, the SA-12 sign sequence (Fines Double, Workers Present) must be used in all TTC
  patterns with workers present.** The portable **R4-103 "Move Over or Slow Down…"** sign is required in
  all applicable work zones on roads with ≥ 2 lanes (p. 1).
- **Speed reduction:** ≤ 10 mph in most cases. More needs District/Regional Traffic Engineer approval and
  steps of ≤ 10 mph. W3-5/W3-5aAZ sign ahead. The speed limit sign is restored about 500 ft past the zone.
  The speed reduction must be documented (p. 2–3).
- **Tapers and device spacing are based on the design / off-peak 85th percentile / existing speed, not the reduced speed** (p. 4).
- **Channelizing device spacing (ADOT practice):**
  - Posted speed ≥ 40 mph: **40 ft on tapers, 80 ft on tangents**.
  - Under 40 mph: ≤ speed (ft) on tapers, ≤ 2 × speed on tangents.
  - **20 ft** in departure tapers and one-lane two-way operations (p. 5–6).
- **Flaggers:** pilot cars on major collectors/arterials where routes can't be closed. **Flagger stations
  stopping traffic at night must be lit by street lighting or portable light towers** (p. 4–5).
- **Cones:** at least 28 in. Retroreflective bands at night. **Strongly discouraged in tapers at night** (p. 6).
- **Warning lights:**
  - Type A flashing on each end of **Type 3 barricades left overnight** or set before sunrise / after sunset.
  - Flashing lights on sign assemblies whenever signs stay up overnight, in the early morning, or late evening.
  - Type C steady-burn for lane guidance at night (p. 3, 12–13).
- **Pedestrians:** keep a 4 ft minimum accessible route (2% max cross slope), on the same side where feasible (p. 3).
- **Work duration categories:**
  - Long-term: > 3 days.
  - **Intermediate: > 1 daylight period up to 3 days, *or night work > 1 hour*.**
  - Short-term: > 1 hr, daytime only.
  - Short duration: ≤ 1 hr.
  - Mobile.
- **Supplemental Applications to use as templates:**
  - **SA-2:** road closure at the far side of an intersection.
  - **SA-3:** one lane closure with a pilot car.
  - **SA-6, SA-7:** using the left turn lane.
  - **SA-8:** intersection with right turn lane, right lane closure, **near side**. Uses W20-1, W9-101, W12-101,
    R3-7R/R3-5R, R2-101, G20-2AZ, R2-103; 350–500 ft on cross streets; 500 ft/1000 ft downstream.
  - **SA-12:** Fines Double. R2-101 with W20-1 at the start; R2-102 every ≤ 2,500 ft; R2-103 at the end;
    double-fine area ≥ 1,000 ft past the first sign; shown only while workers are present.
  - **SA-4:** the brake-check flagger must be a **uniformed police officer**.
- **Arizona sign codes** the layout engine needs: G20-2AZ, R2-101/102/103, R4-103, W3-5aAZ, W9-101, W12-101.

### ADOT Traffic Safety for School Areas Guidelines (2006) — `adot-school-2006` [source]
- Covers **Arizona School Crossings (ARS §28-797)**: yellow crosswalks, 15 mph "School in Session"
  portable signs, adult crossing guards, and an operating agreement setting the hours.
- Not used within 600 ft of a STOP sign, signal, or another school crossing on the same road. Not used at high schools.
- **Does not address work zones or require police in work zones.** It is useful for **detecting**
  school crossings and their hours, which the tool needs to flag work near a crossing.

---

## The school-zone police requirement

You reported that work in a school zone requires a police officer. **None of the documents provided
so far say this**, including the city manuals, the AZ Supplement, and ADOT's school area and TTC guidelines.
Possible sources:
1. Mesa's or Chandler's manuals (not yet provided).
2. The Phoenix TBM (which Tempe adopts).
3. Permit conditions the city adds during review (Tempe §4.4 and Gilbert's "Police Officer Required" box allow this).
4. Utility company policy.

**How TCP-Auto handles it for now:** the school-zone police trigger is in each city file as
`source: user-reported`, `verified: false`. The app **applies it** (it's the safer choice) and the report
shows the reason as "School zone (utility practice; confirm with city)". Once the actual source is found,
the citation gets updated.

---

## Implications for TCP-Auto

1. **Rule chain for Tempe** = federal MUTCD 11 → AZ Supplement → **Phoenix TBM** → Tempe overrides.
   The rules engine must support a city "adopting" another city's manual.
2. **Peak-hour windows differ by city.** Mesa 6:30–8:30 / 16:00–18:00, Tempe 7:00–8:30 / 15:30–18:30,
   Gilbert 5:30–8:30 / 15:30–19:00. The timeline check uses the city's window.
3. **Gilbert's 300 ft signalized intersection rule** is the first concrete police trigger. It needs signal locations (§3.5 of the plan).
4. **Night work** in Tempe is checked against City Code §20-8: residential proximity within 500 ft,
   season, weekends. That means the tool needs **zoning or land use near the site** (residential vs. commercial), from city GIS or OSM `landuse`.
5. **Tempe's TCP content list** becomes the minimum content of the report. It's a good baseline for all cities.
6. **Arterial lane closures in Gilbert need an arrowboard. Short-term operations in Tempe need an arrow panel and a 50 ft cone taper.**
7. **Night operations:** lit flagger stations, flashing lights on signs, Type A lights on Type 3 barricades,
   and avoiding cones in tapers (use drums or vertical panels) per ADOT.
8. **Device spacing:** use ADOT's 40/80 ft practice for ≥ 40 mph. City streets under 40 mph use MUTCD speed-based spacing.
9. **Double-fine SA-12 signing** is mandatory on state highway work zones with workers present. Whether
   cities require it on city streets is still open.
