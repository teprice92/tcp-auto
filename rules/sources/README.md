# Rule Source Documents

This file lists every document the jurisdiction rule files (`rules/**.yaml`) are based on.
Each rule's `cite.source` refers to an `id` in the tables below.

The original PDFs are **not committed** to the repo, because of their size and because agencies
update them. Keep local copies under `rules/sources/pdf/` (ignored by git) with the filenames
listed here.

**Status key**
- `provided`: the user supplied the document, and rules were read directly from it.
- `web-summary`: found only through web search summaries, not read in full. Rules from these are marked `verified: false`.
- `missing`: not yet obtained.

## Provided

| id | Jurisdiction | Title | Edition / date | Final? | File |
|---|---|---|---|---|---|
| `tempe-tbm-2016` | Tempe | City of Tempe Traffic Barricade Manual | Updated March 2016 | Final | `COT_Barricade_Manual_June16_Final_LoRes.pdf` |
| `gilbert-te-app-2014` | Gilbert | Traffic Engineering Application packet (application, checklist, TCP application, road closure request, dirt haul requirements, Temporary Traffic Control / Work Zone Requirements) | Aug 2014 | Final (age: check for a newer version) | `Traffic_Engineering_Application.pdf` |
| `qc-full-closure-2023` | Queen Creek | Temporary Traffic Control Full Roadway Closure Policy | Updated Aug 3, 2023 | Final | `Public_Works_Town_Policy__TTC_Full_Road_Closure_Policy_080323.pdf` |
| `qc-dspm-notes-2007` | Queen Creek | Design Standards and Procedures Manual: Construction Notes (General, Paving, G&D, SWPPP, Signing & Marking) | Adopted Oct 2007, modified 2008; signing notes rev. 3/2015 | Final (old) | `Construction_Notes.pdf` |
| `adot-ttcdg-2025` | ADOT | Temporary Traffic Control Design Guidelines | April 2025 (file metadata says "2025-draft"; figures marked "Revised April 2025") | Check: may be draft | `TempTrafficCtrlDesignGuidelines.pdf` |
| `az-supp-mutcd11-2026` | Arizona | Arizona Supplement to the MUTCD, 11th Edition | January 2026 | Final | `Arizona-Supplement-MUTCD.pdf` |
| `adot-school-2006` | ADOT | Traffic Safety for School Areas Guidelines | 2006 (Rev. 10/06) | Final | `adot-traffic-safety-for-school-area-guidelines.pdf` |

## Web summary only (still need the actual document)

| id | Jurisdiction | Title | Where found | Notes |
|---|---|---|---|---|
| `mesa-ttcm-2ed` | Mesa | Temporary Traffic Control Manual, Second Edition | mesaaz.gov (draft PDF); city permit page says effective July 2026 | Need the final adopted version |
| `mesa-ttcm-1ed-2017` | Mesa | Temporary Traffic Control Manual, First Edition | atssa.com copy | Superseded by the 2nd edition |
| `qc-tcp-app` | Queen Creek | Traffic Control Plan application / requirements form | queencreekaz.gov | Lead time, deputy requirement |
| `chandler-edsm` | Chandler | Engineering & Design Standards Manual, Ch. 7 Traffic Barricade Design (incl. §7.6.5.1 Police Officers) | chandleraz.gov | Only the off-duty officer scheduling line was visible |
| `chandler-udm148` | Chandler | Utility Permit Manual UDM-148 (June 2024) | chandleraz.gov | Utility-specific; high priority |
| `phx-tbm-9r` | Phoenix | Traffic Barricade Manual, Revised 9th Edition (2021) | phoenix.gov | **Adopted by Tempe** as its base manual, and referenced by Queen Creek |
| `aj-code-row` | Apache Junction | City code: right-of-way encroachment permits | codelibrary.amlegal.com | Permit required; no TCP specifics found |

## Missing

| Jurisdiction | Needed |
|---|---|
| Federal | FHWA MUTCD 11th Edition, Part 6 (TTC) and Part 7 (School Areas). The baseline numbers in `federal/mutcd-11.yaml` need to be checked against it. |
| Mesa | Final TTC Manual, 2nd Edition |
| Chandler | Engineering & Design Standards Manual Ch. 7; UDM-148 Utility Permit Manual |
| Phoenix | Traffic Barricade Manual (latest), needed because Tempe adopts it |
| Apache Junction | Any traffic control plan requirements / engineering standards |
| Maricopa County (MCDOT) | ROW permit and traffic control requirements |
| Pinal County | ROW / encroachment permit and traffic control requirements |
| MAG | Uniform Standard Specifications & Details, traffic control sections (Queen Creek and others build on MAG) |
| All East Valley cities | **Written source for "school zone requires a police officer."** None of the documents above contain it (see `docs/jurisdiction-research.md`). |
