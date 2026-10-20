# BRAHMO Clinical AI — Final Architecture and Doctor-Readiness Plan

**Candidate:** [YOUR NAME] · **Submission date:** 20 October 2026 · **Opened:** [hh:mm IST] · **Submitted:** [hh:mm IST]
**Basis:** assessment pack (00–03) and the supplied end-to-end prototype (Streamlit → drug graph → rail → lexical retrieval → Supabase audit); prototype findings are marked **[PROTO]**. Fixed laws = L1–L12 (fences = L12).
**Tags:** `D#` = Decision Register row (S2); `F#` = added factor (S6); `[DEP …]` = material departure from a section, position (P01–P09) or stage (A–G).
**Honesty note:** nothing here claims a completed benchmark, sign-off or legal opinion. Legal items show their verification state in S4.

---

## S1 · Final Architecture

### 1.1 Posture
A clinician-facing reference-and-cross-check layer: it resolves Indian brand strings to ingredients, runs deterministic cross-checks, answers reference questions only from verified, versioned, citable evidence, and hands every output to the doctor for approval. It never calculates a patient dose, ranks diagnoses, scores triage, drafts a treatment plan or addresses patients (L12). **Retained:** P01 structured-first routing (**D5**), P04 supersession ≠ conflict (**D3**), P05 trust tiers, P06 sufficiency gate (strengthened, **D3**), P09 scope. **Changed:** P02, P03, P07, P08 and Stage D precedence (S2/S6).

### 1.2 Diagram (logical; may deploy as few services)

```
 ┌── Z0 DEVICE (untrusted) ───────────────────────────────────────────────┐
 │ Doctor PWA: per-user login · idle lock · encrypted offline cache        │
 │ (signed drug-master+rule snapshot with valid_until; queued actions)     │
 └──────────────┬──────────────────────────────────────────────────────────┘
                │ TLS · signed tenant/user token
 ┌── Z1 EDGE (India region) ───▼──────────────────────────────────────────┐
 │ API gateway: authn/z · tenant context · rate limit · input sanitiser    │
 │ (all transcripts/docs = DATA, L9) · capability flags (per molecule/     │
 │ specialty/language) · kill-switch                                       │
 └──────┬──────────────────────────────────────────────────────────┬──────┘
        │                                                          │
 UPSTREAM CONTRACTS (§1.4)                                           │
 Scribe: Rx entities+transcript refs ─►┐   ┌◄─ Patient-context snapshot │
                                       ▼   ▼                          │
 ┌── Z2 PHI ZONE (India, RLS per tenant, per-tenant keys) ─────────────▼──┐
 │ ORCHESTRATOR (deterministic router)                                     │
 │  ├─ Intent+fence classifier ──► REFUSE (L12) / structured / reference   │
 │  ├─ MEDICATION-REVIEW PATH (no model call, L4)                          │
 │  │    resolve → ambiguity queue → FDC→moiety → checks → 8-state results │
 │  ├─ REFERENCE PATH                                                      │
 │  │    de-identify → scope-first retrieve → sufficiency gate →           │
 │  │    [LLM compose, Z4] → claim verifier → extractive fallback (labelled)│
 │  └─ APPROVAL SERVICE: DRAFT→PENDING→APPROVED(hash-bound)→EXPORTED       │
 │ AUDIT LOG (append-only, hash-chained) ◄── every step                    │
 └───────┬──────────────────────────────────────────┬─────────────────────┘
         │ read-only, versioned snapshots           │ de-identified text only
 ┌── Z3 KNOWLEDGE (no PHI, global + tenant overlays) ─┐   ┌─ Z4 MODEL PROVIDER ─┐
 │ Drug master · regulatory event store · rule sets ·  │   │ pinned model, zero  │
 │ chunk store+hybrid index · source registry ·        │   │ retention, no PHI,  │
 │ release manifests · review queues (human lane)      │   │ no tools, schema out│
 └─────────────────────────────────────────────────────┘   └─────────────────────┘
 Output: doctor card (statuses, citations, coverage, versions) → approve/edit/reject
         → saved note / PDF export (generic names first, version footer) → audit
```
**Trust boundaries:** Z0→Z1 (authN, token), Z1→Z2 (tenant context), Z2→Z4 (only de-identified composition payload, scanned), Z3→Z2 (read-only signed snapshots; Z3 never receives PHI). Human review lane (clinical pharmacologist, QA, counsel) writes only to Z3 via signed release manifests.

### 1.3 Components and responsibilities
| Component | Responsibility | Key entities |
|---|---|---|
| Gateway | Identity, tenant scoping, flags, kill-switch, sanitising | `Tenant, User, Session, CapabilityFlag` |
| Orchestrator | Fence check, routing, versions pinning per request | `Request{id, snapshot_ids, model_pin}` |
| Drug master | alias→brand→product→moiety graph; FDC decomposition; ambiguity queue | `Alias, Product, Ingredient(moiety), Mapping{version}` |
| Regulatory event store | Effective-dated, scoped, superseding events | `RegEvent{notif_id, effective_from/to, scope{pop,form,party}, supersedes, source_loc}` |
| Rule store | Reviewed interaction/allergy/pregnancy/duplicate rules | `Rule{id, version, reviewer, valid_until, evidence}` |
| Knowledge service | Chunk store, hybrid index, release manifests, withdrawal | `Source, Edition, Unit, ReleaseManifest` |
| Approval service | Hash-bound doctor approval, pending queue, re-check on approve | `Output{hash}, Approval{actor, hash, snapshot}` |
| Audit | Append-only hash chain; PHI-minimised; replay | `AuditEvent` |
| Review lane | Queues, two-key changes, corrections triage | `ReviewItem{reason_code, tier}` |

### 1.4 Upstream contracts (no access to Scribe/patient-context code assumed)
**Scribe → BRAHMO** (`schema_version` semver; idempotent by `entity_id`; BRAHMO rejects tenant/encounter mismatch):
`entity_id, encounter_ref, tenant_id, encounter_mode{in_person|tele}, captured_at, raw_string, script/lang tag, asr_confidence, transcript_span{ref, start, end}, brand?, strength{value,unit}?, form?, route?, frequency_text (opaque; BRAHMO never computes with it), duration_text, field_status{present|missing|uncertain|conflicting}, scribe_model_version, doctor_edited{bool}`.
Scribe supplies hypotheses, never identity. BRAHMO returns `resolution{state, candidates[], reason_code, mapping_version}` and an ack; unresolved items go to **doctor disambiguation** in the same screen (not silently dropped).
**Patient-context → BRAHMO** (versioned snapshot, read-only, minimal): `snapshot_id, as_of, subject_pseudonym, tenant_id, authorization_ref`, and per field `{value, unit, observed_at, source, status{known|unknown|not_collected|stale|conflicting}}` for: age band + DOB-derived age, sex, pregnancy, lactation, allergies (coded + free text), renal/hepatic flags, comorbidity codes, current medicines. **Weight is deliberately not requested** (no dose calculation, L12; data minimisation). Each field has a `max_age` policy; stale → check reason `STALE_CONTEXT`.
**BRAHMO → doctor surface:** the `Output` object (§5.2) with every check state, citations, coverage list and version stamps.

### 1.5 Doctor path (end to end)
Input (Scribe entities or typed question) → gateway/tenant → fence + intent classification → patient-context fetch (snapshot pinned) → drug/regulatory retrieval (structured) and/or evidence retrieval → deterministic checks → clarification (ambiguity, missing context; one batched prompt) → draft card → doctor review/edit → **approval bound to output hash and snapshot IDs** → delta re-check at approve time → save/export → audit. Every arrow writes an audit event.

### 1.6 Worked example A — reference question (all content FICTIONAL)
*Q (Telugu–English mix, normalised): "Demo Guideline 3: adult dosing text for Compound ZETA in renal impairment?"* — fence check passes (reference text, no patient calculation) → class `dose-reference-text`, required slots {moiety, population=adult, condition=renal impairment} → hybrid retrieval with hard scope filter (edition status = current, population ∋ adult, jurisdiction India) → gate: slot "renal impairment" found in unit `DG3:T4:r2` → composed answer shows the **table row verbatim**, units, footnote b and edition date; **no per-patient number computed**. If the gate fails (no renal row): *"I can't confirm renal-impairment dosing for ZETA from the verified Indian corpus. Missing: renal-impairment table. Edition 3 (2026-02-01) covers adults only."*
### 1.7 Worked example B — medication review (FICTIONAL)
Rx lines: `Zedotab-250` (FDC: ING-A 250 mg + ING-B 100 mg), `Alphacin 500` (ING-A 500 mg), `Brandex` (two strengths exist; none given).
| Check | State | What the doctor sees |
|---|---|---|
| Duplicate moiety | **HIT** | ING-A in Zedotab-250 and Alphacin 500 (labelled strengths shown; no daily total computed — see D6) + cited reference text |
| Brandex identity | queued `AMBIGUOUS_STRENGTH` | pick 250/500 (one tap) — until then every check on it is `UNVERIFIED_INPUT` |
| Restricted/banned FDC | **CHECKED_NO_HIT** | "No event matches in feed dated 2026-10-20, scope: adult/tablet" |
| Interaction ING-A×ING-B | **NOT_CHECKED** | "No reviewed rule for ING-B; this is not a negative result" |
| Roll-up banner | HIT + coverage gaps | never "safe"; lists what was and was not evaluated |
Doctor approves → hash + versions stored → export lists **generic names first** (S4-R12).

---

## S2 · Decision Register
Format per row: **Current → Choice → Why → Strongest rejected alternative → Accepted cost → Validation.** Details live in S3–S5.

| # | Area | Current | Choice | Why | Strongest rejected alternative | Accepted cost | Validation |
|---|---|---|---|---|---|---|---|
| **D1** | Grounding sources | P03 ladder; Stage D tenant protocol "outranks" national | Keep ladder, **retain** order Indian-verified → tenant protocol → international (same verification pipeline, "non-India" badge) → model knowledge for *background class only* and never inside the medication path. **Change:** tenant protocol is shown first *for that tenant* but a disagreement with national guidance is displayed side-by-side, never silently outranking. Precedence is a reviewer-owned versioned table per (topic, population) `[DEP P03, Stage D]` | Doctors need local protocols; hiding national disagreement is a medico-legal and safety hazard | Licensed global compendium (e.g., UpToDate-type) as primary | Narrower Indian coverage → more abstentions; some questions answered only as "non-India source" | Precedence-table review per topic; conflict-display tests (S7-T6); coverage atlas |
| **D2** | Chunking | "Decision-unit chunks; bulk token-chunking banned" | **Retain and tighten:** a chunk = one *clinical assertion unit* with a mandatory **scope envelope** (population, form, indication, edition, jurisdiction, exceptions), parent pointer, and tables stored as **row-records** carrying header, units and footnotes; cross-page relations stored as explicit links. Never truncate at display | Token windows split a dose from its exception/footnote — a silent wrong claim | Sliding-window + overlap, LLM-summarised parents | Slow, human-reviewed ingestion; fewer sources at launch | Chunk-fidelity audit: 100% of consequential units human-checked; extraction dual-agreement + exact-quote binding (retained Stage B) |
| **D3** | Retrieval | "Hybrid retrieval", P06 gate, P04 | **Scope-first hybrid:** hard metadata filters (current edition, population, form, tenant, language) → BM25 + dense → rerank → **deterministic class-slot sufficiency gate** → LLM compose only from selected units → **claim verifier** (numbers/units/negations must literally appear in the cited span) → drop unverified sentences → if too many dropped, show extractive view (visibly labelled). Retrieval has **no model call**, so it is replayable (L8) | Relevance ≠ applicability ≠ support; each needs its own check | Dense-only / long-context stuffing / graph-RAG | Two indices to maintain; verifier drops useful prose (lower fluency); latency budget pressure | Separate relevance/applicability/support metrics (S7-T3..T5); injection corpus |
| **D4** | Embedding / index | Unspecified | **Self-hosted open-weight multilingual encoder in the India region** (final pick by recall on S7 retrieval set); vectors in the same transactional store as units (pgvector-class), **one index build per release manifest**, re-embed gated by regression `[fills Stage C/G]` | Residency, versioning, replay; curated corpus is small (≤ ~10⁶ units) | Managed external vector SaaS | We run it; recall ceiling vs. specialised ANN (acceptable at this scale) | Recall@k + hard-negative sets; index rebuild reproducibility check |
| **D5** | Drug data | Graph with free sources; overlay never redefines canon (P01) | **Retain** P01 and overlay rule. Canon from CDSCO approvals/notifications, NLEM, NPPA price lists, Jan Aushadhi list + pharmacopoeial/formulary data where licensed; **ingredient identity at moiety level with salt/ester normalisation and external crosswalk ids** (RxNorm/ATC where licence permits). **Add P07 mechanism (S3.5)**: quarantine on sibling/cross-source contradiction; single-source rows cannot feed the rail unreviewed; two-key review for any change that flips a safety state. **Add** look-alike-sound-alike (LASA) registry | A poisoned canonical row must be *catchable*; brand strings are not identity | Buy one commercial brand DB as truth | Large unresolved long tail → doctor disambiguation taps; curator load | Held-out mapping key with denominators (S7-T1); seeded-poison tests |
| **D6** | Safety-check boundaries | P02: ingredient-level checks **plus cumulative exposure totalled across the prescription** | **Retain** FDC decomposition and duplicate-moiety detection. **Remove** cumulative mg totalling/comparison to a maximum: it multiplies strength × patient frequency and compares to a limit — a patient-specific dose calculation (L12). Show labelled strengths and the *cited reference maximum as text* for the doctor `[DEP P02 · F1]` | Fixed fence beats a useful feature | Compute daily totals vs label maximum | Loses the quantitative paracetamol-style double-dose catch (mitigated by HIT + cited text) | Fence tests: no function accepts frequency; code-scan gate; reviewer sign-off |
| **D7** | Model/provider posture | Frontier LLM wrapper | Model-agnostic gateway; **LLM only for composition** (and offline extraction assist, always human-reviewed); pinned version; zero-retention contract; **no PHI in payload** (de-identified); no tools, JSON-schema output; no fine-tuning on PHI or sources. Fallback tiers visible; no silent provider swap (L10/L11) | Smallest model surface; safety outside LLM (L4) | Self-hosted open-weight generator as sole path | Provider dependence; composition outage → extractive view only | Pinned-model regression (S7-T8); egress and payload scans |
| **D8** | Data residency | Unstated | PHI at rest and in processing **in India**; telemetry PHI-free; non-PHI composition may use a provider outside India only if counsel confirms transfer posture; else composition is disabled | DPDP s.16 allows transfer unless restricted; sectoral/contract rules may bind; keep PHI out of reach regardless | Global multi-region | Fewer providers, higher latency, cost | Network egress allow-list tests; DPA review |
| **D9** | Multi-tenancy | Tenant baseline (A); cross-tenant tests only at E | Row-level security on every PHI table + **per-tenant envelope keys**; tenant overlay in separate namespaces; overlay can *add* warnings or local preferences but can **never suppress a rail HIT or edit canon**; cross-tenant negative suite becomes a **Gate 1** item `[DEP Stage E → Gate 1]` | A leak is catastrophic and pilot already serves | DB-per-tenant | RLS bugs have wide blast radius → heavy negative testing | Cross-tenant suite incl. fuzzed IDs, cache and index isolation |
| **D10** | Audit | "Byte-consistent replay proven end to end" | Append-only, **hash-chained** events with actor, tenant, all version pins (data snapshot, rules, prompt, model, embedding, index), retrieved unit ids, check results, output hash, approval hash. PHI stored as references + encrypted payload store with retention policy. **Redefine replay:** deterministic parts re-run byte-identically; LLM text is *stored* and re-rendered, not regenerated `[DEP Stage E]` | LLM output is not reproducible; claiming it is would be a false guarantee | Log everything in plain text | Storage; erasure vs retention tension (S4-R17) | Replay drill: random sample reproduces card exactly; chain-verification job |
| **D11** | Doctor approval | "Doctor confirms" (prototype: a checkbox) | **Hash-bound approval**: approves a specific output + snapshot IDs; any edit invalidates; delta re-check at approve; pending items expire | Approval must be evidence | Implicit acceptance on save | One extra tap | Approval-forgery and stale-approval tests |
| **D12** | Alert governance | "High-severity only", tune by telemetry | Interrupt only for rail HIT of reviewer-set severity ≥ *major* and restricted/banned FDC (+ tele-prohibited). Everything else = passive chips. **One** per-encounter coverage banner replaces repeated NOT_CHECKED noise. Telemetry: acted/overridden/dismissed with reason; high dismissal triggers *rule review*, never auto-suppression | Unknown-state spam is the hidden fatigue source | Alert on every non-clean state | Some real-but-minor findings are passive | Pilot acted-vs-dismissed analysis; reviewer-set thresholds |
| **D13** | Languages | Not specified | Input: multilingual/transliterated, normalised before resolution. Output: English authoritative for clinical text; UI chrome and status phrases in major languages from a **pre-translated, reviewed phrase table**; machine-translated gloss off by default per language until validated. **No AI-generated patient-language instructions** (fence) | Translation errors in dose/safety text are unsafe | Auto-translate all answers | Hindi/Telugu etc. narrative stays English at first | Per-language coverage matrix (S8) |
| **D14** | Offline/shared devices | Mentioned, unspecified | Signed snapshot with `valid_until`; offline checks run only inside validity, stamped "data as of …"; offline Q&A unavailable; queued actions encrypted per user; short idle lock; wipe on logout | Safe degradation visible | Full offline Q&A | Reduced function in rural settings | Offline expiry and shared-device tests |

---

## S3 · Grounding & Sources Plan

### 3.1 Source catalogue
Version/date column states what is known now; **every edition is pinned at ingestion** and re-verified. "Rights" = my reading; counsel confirms (S4). Status: F free-to-access · L licensed · C curated by BRAHMO reviewers.
| Source | Purpose | Authority/coverage | Version/date | Status | Limitations |
|---|---|---|---|---|---|
| ICMR Standard Treatment Workflows; MoHFW National Standard Treatment Guidelines (2016 ed., verify latest) | First-/second-line reference, outpatient workflows | National research council / MoHFW | Editions pinned at ingestion | F; reuse **unverified** | Summaries; incomplete drug/dose detail |
| National programme guidelines (NTEP, vector-borne, immunisation/UIP, maternal health) | National-programme answers | Programme authority in domain | Latest pinned per programme | F; reuse unverified | Frequent updates; regimen changes by circular |
| National List of Essential Medicines | Availability/essentiality, alternatives | MoHFW | 2022 | F | Not a treatment guideline |
| NPPA price notifications (DPCO 2013) | Ceiling prices; price-controlled flag | Statutory regulator | Monthly/ad hoc | F | Price ≠ availability |
| CDSCO approvals, gazette notifications (s.26A; Sch. H/H1/X of Drugs Rules 1945) | Regulatory event store | Statutory | Event-dated | F | Stays/contests; inconsistent PDFs |
| PMBI Jan Aushadhi product list | Generic alternatives, affordability | PMBI | Pinned list date | F | Availability varies by kendra |
| National Formulary of India / Indian Pharmacopoeia | Monographs, dose-form reference | IPC | Editions per IPC | **L** | Licence needed to index/display |
| Specialty societies (e.g., FOGSI, IAP, API) | Specialty depth, immunisation schedules | Professional bodies | Per document | Mixed; **rights TBC** | Copyright held by societies; may conflict with national programmes |
| Hospital/tenant protocols and antibiograms | Local practice | Tenant | Tenant-dated; antibiogram **expires** | Tenant contract | Unreviewed by BRAHMO → always labelled |
| Curated critical interaction/allergy/pregnancy rules | Rail content | **C**: authored by BRAHMO reviewers citing primary labels/literature, signed by clinical pharmacologist | Rule version + `valid_until` | C | Coverage = prescribing-weighted subset, not comprehensive |
| CDSCO-approved prescribing information / US/EU labels | Evidence for rules; international tier | Regulators | Label date | F (access) | Reuse of excerpts to confirm; non-India badge |
| WHO Model List / AWaRe | Background, antimicrobial stewardship | WHO | Pinned | F access; **non-commercial licence (CC BY-NC-SA)** | Excerpts in a commercial product need counsel → link-out only |
| Identifier crosswalks (RxNorm, WHO ATC) | Moiety/class ids | NLM / WHOCC | Release pinned | RxNorm terms; ATC commercial licence **TBC** | Not India-brand aware |

### 3.2 Access ≠ permission — rights matrix (default until counsel clears)
| Use | Government/programme docs | Society guidelines | Licensed compendia (IP/NFI) | Tenant protocols | Open-licence (e.g., US labels) |
|---|---|---|---|---|---|
| Access/read | Yes | Yes | After licence | Yes | Yes |
| Store raw copy | TBC per document | **No** until licence | After licence | Yes (contract) | Yes |
| Extract structured facts | TBC | **No** | After licence | Yes | Yes |
| Index (embeddings are derivative) | TBC | **No** | After licence | Yes | Yes |
| Display excerpts | Short, cited, TBC | link-out only | Per licence | Yes (own users) | Yes |
| Train/fine-tune | **No** | **No** | **No** | **No** | No (not needed) |
**Consequence:** where indexing is not cleared, that source is *disabled* or link-out only, and the coverage atlas shows "source not licensed".

### 3.3 Knowledge lifecycle
1 **Acquire** (manifest: URL, retrieved_at, hash, licence record, edition) → 2 **Raw** (immutable) → 3 **Extract** (layout-aware, two independent extractors; disagreement → human; **exact-quote binding** of each unit to a span/page/cell) → 4 **Structure** (assertion units + table row-records + scope envelopes + links) → 5 **Review** (consequential units 100% human; background units sampled) → 6 **Version/publish** (signed release manifest, diff-first changelog "what changed, in which source, effective when") → 7 **Eligibility** (status `verified-live` only; effective_from/to; population/form) → 8 **Serve** → 9 **Update** (feed watch; diff; re-review only changed units; old edition kept as `superseded`, replay-only) → 10 **Withdraw** (tombstone; retrieval off immediately; saved/exported outputs citing it are flagged and the approving doctor notified).

### 3.4 Chunk and citation example (fictional)
```json
{ "unit_id":"DG3:T4:r2", "type":"table_row", "source":"Demo Guideline (fictional)",
  "edition":"3", "effective_from":"2026-02-01", "status":"verified-live",
  "scope":{"population":"adult","form":"tablet","indication":"renal impairment","jurisdiction":"IN"},
  "locator":{"page":12,"table":4,"row":2,"footnotes":["b"]},
  "header":["eGFR band","Reference text","Unit"],
  "cells":["30–59","[verbatim cell]","mg"], "exceptions_ref":"DG3:T4:fn-b",
  "review":{"extract_agree":true,"human":"RV-014","date":"2026-03-02"},
  "content_hash":"sha256:…" }
```
Citation shown to the doctor: *Demo Guideline ed.3 (eff. 2026-02-01), p.12, Table 4 row 2, footnote b.*
**Three separate validations:** *relevance* (did we retrieve it — recall@k), *applicability* (does the scope envelope match the case — deterministic, 100% for consequential claims), *support* (does the cited span literally support the claim — verifier + labelled entailment set). One cannot substitute for another.

### 3.5 Conflicts, supersession, precedence, poisoning
Supersession: newer edition serves, older retained flagged (P04 retained). **Genuine concurrent conflict** (e.g., national programme vs society, same population): show both with dates; precedence table influences *order*, not suppression. Local vs national: see D1. International: only verified units, badge, never merged with Indian text. **P07 mechanism:** nightly and on-ingest checks — sibling composition consistency; cross-source composition disagreement; strength/unit outliers (e.g., mcg/mg ×1000); price vs NPPA ceiling; active-product vs banned-FDC match (P08); single-source flag; two-key review for safety-flipping edits → status `QUARANTINED` serves as `UNVERIFIED_INPUT`/`NOT_CHECKED`, never as clean.
**Missing permissions/sources → consequence:** no licensed interaction database → rail stays at curated scope with explicit `NOT_CHECKED` elsewhere; no society licence → specialty depth limited to government sources; no pharmacopoeial licence → no monograph display.

---

## S4 · Rules of Behavior for India

### 4.1 Product rules
Format: **condition → required/prohibited behaviour → reason → enforcement → verification/approval.**
| # | Condition | Behaviour | Reason | Enforcement | Approval |
|---|---|---|---|---|---|
| R1 | Request for patient-specific dose, mg/kg, titration | **Refuse**; offer cited reference text | L12 fence | Fence classifier + no dose function in code | Clinical lead |
| R2 | "Most likely diagnosis / how severe / triage", or any patient-facing advice | **Refuse** | L12; likely SaMD territory (S4.2-B) | Classifier, refusal tests | Counsel |
| R3 | Any consequential claim (dose text, safety, regulatory status) | Show only if cited with source/edition/date/locator, else "cannot confirm — missing: X" | L2, L3 | Claim verifier blocks | Clinical review |
| R4 | Model-only knowledge | Allowed only for background class, labelled "not from verified sources"; never in medication path | L2 | Class gate | Clinical lead |
| R5 | Any check not fully evaluated | Show its exact state; never "safe/clear" wording | L5 | Phrase-table lint | QA |
| R6 | Ambiguous brand/strength/form | Queue with reason code; doctor picks | L6 | Resolver returns no ingredients | QA key |
| R7 | Regulatory status asked | From event store only: status, notification id, effective dates, scope, stays | L7 | No boolean field in schema | Regulatory reviewer |
| R8 | Court stay/interim relief limited to named parties or stock | Show "contested — scope per order"; do not render as lifted | Event scope | `party` scope in event | Counsel |
| R9 | Tele-consult (`encounter_mode=tele`) and drug in tele-prohibited category | Flag regulatory HIT | Telemedicine Practice Guidelines | Rule by category | Counsel |
| R11 | Pregnancy/lactation/paediatric question | Reference text with scope badges; if population mismatch → abstain | P09 | Hard scope filter | Specialty reviewer |
| R12 | Export/print of a prescription-related note | Generic (ingredient) names first; brand optional second | IMC 2002 generic-name duty | Template | Counsel |
| R13 | Commercial influence | No sponsored ranking, brand promotion or pharma content | UCPMP/IMC ethics | Ranking audit | Counsel |
| R14 | Document/transcript contains instructions | Treated as data; ignored | L9 | Structural separation, injection suite | Security |
| R16 | Capability without clinical sign-off or legal clearance | Flag OFF for that molecule/specialty/language | Handover gate | Capability flags | Handover owner |
| R17 | Erasure request vs audit/medical-record retention | Erase PHI payloads; keep pseudonymised hash chain; retention per counsel | DPDP s.8(7) vs record duties | Retention policy | Counsel |
| R18 | Minor patient | Process only for health service by clinician; no behavioural tracking/analytics | DPDP s.9 + healthcare exemption (verify) | Analytics off for minors | Counsel |
| R19 | Doctor correction | Capture type; never auto-publish; PHI-stripped | Truth is reviewed | Review queue | Reviewer |

### 4.2 Legal/regulatory register
Types: **L**=law, **G**=guidance, **C**=contract, **P**=product policy, **I**=my interpretation. "Verified" means I read current secondary or primary reporting in this exercise; **primary gazette text still needs counsel confirmation**.
| Item | Source/link | Version, date, status | Provision | Applicability & technical consequence | Verification |
|---|---|---|---|---|---|
| **A. DPDP Act 2023 + DPDP Rules 2025** (L) | meity.gov.in; PIB 17 Nov 2025 (static.pib.gov.in) | Rules notified 13 Nov 2025 (gazette 14 Nov; sources differ). Rules 1, 2, 17–21 immediate; Rule 4 consent managers ~13 Nov 2026; Rules 3, 5–16, 22–23 on **13 May 2027**. Reported MeitY proposal to shorten timelines: **not verified as notified** | s.4–7 consent/legitimate use; s.8 safeguards, breach, erasure; s.9 children; s.16 transfer | Clinic = fiduciary, BRAHMO = processor (I). Build to final duties now: consent record, breach pipeline, erasure, minimal PHI, India residency, no secondary PHI use | **Unverified:** rule numbering, healthcare exemption for minors — counsel; pilot only with explicit clinic consent |
| **B. CDSCO Guidance on Medical Device Software** (G on L: Drugs & Cosmetics Act 1940, Medical Devices Rules 2017) | cdsco.gov.in; Doc CDSCO/MD/GD/MDSW/01/2026 | Draft 21 Oct 2025; final circulated **21 Jul 2026** (per law-firm summary) | Software with clinical decision support, treatment recommendation or triage may be a medical device; intended-use statement must say whether it only informs or drives a decision | Interaction/restricted-FDC alerts are plausibly **CDS** → treat as in scope until a memo says otherwise. Intended use: *clinician reference + cross-check; no diagnosis/triage/treatment recommendation*. Plan QMS, risk file, post-market surveillance | **Class (A–D) unverified** — regulatory-affairs + counsel memo; **rail stays in supervised pilot until issued** |
| **C. Telemedicine Practice Guidelines 2020** (L/G) | MoHFW/NMC, 25 Mar 2020 (Appendix 5 of IMC 2002 regs) | In force per my reading; verify later amendments | Drug-list categories for remote prescribing | `encounter_mode` + category rule (R9). Only if workflow used remotely | Counsel to confirm applicability and lists |
| **D. IMC Professional Conduct Regulations 2002** (L) | NMC | NMC adopted them again after putting the 2023 regulations in **abeyance** (Aug 2023, per reports); verify no later notification | Generic-name prescribing; ethics/advertising | R12, R13; export format | Counsel |
| **E. Drugs & Cosmetics Act s.26A, Rules 1945 Sch. H/H1/X** (L) | CDSCO gazette | Events seen in reporting: 349 FDCs (Mar 2016), 328 (Sep 2018), **156 (Aug 2024; Delhi HC interim order for petitioners 29 Aug 2024)**, **16 (20 Jun 2026)** — trade-press dated; gazette needed | s.26A prohibition in public interest | Event store with `scope.party`, supersession, stay; stock sell-through not assumed (P08) | Regulatory reviewer loads each event from **gazette text**; press dates are leads only. Pharmacovigilance: ADR reporting shown as link-out to PvPI (clinician duty unverified) |
| **F. CERT-In Directions (28 Apr 2022) / IT Act s.70B; SPDI Rules 2011** (L) | meity/cert-in | 6-hour incident reporting and 180-day log retention in India (my recollection); SPDI reportedly continues until DPDP core duties | Incident reporting; sensitive personal data | Incident runbook; India log retention | **Unverified recollection** — counsel/security |
| **G. Provider and source contracts** (C) | — | Not supplied | Zero-retention, India processing, sub-processors; source licences | **Capability stays off** until signed | Counsel + procurement |
**What cannot be enabled until resolved:** (1) rail/CDS outside supervised pilot — memo B; (2) any source's indexing/display — rights matrix; (3) LLM composition — DPA + payload scan + transfer view; (4) tele-mode rules — memo C; (5) minors' analytics — A.

---

## S5 · Correctness & Safety Design

### 5.1 Deterministic vs generated
| Deterministic (no model) | Generated (model allowed) | Never generated |
|---|---|---|
| Fence classification (rules + tested classifier), resolution, FDC decomposition, regulatory status, all checks, roll-up, scope filtering, retrieval, sufficiency gate, verifier, approval, audit | Composition of an answer *from selected units* (then verified); offline extraction assist (human-reviewed) | Doses, safety statements, regulatory status, check results, patient instructions |
**Boundary enforcement:** the check package imports no model client (build-time dependency lint); the check service has no outbound network route; CI fails if a model identifier appears in a check trace. The fence classifier is deterministic-first (keyword + structure) with a conservative default to refuse.

### 5.2 Core objects
**DrugIdentity:** `product_id, brand, manufacturer, form, route, release_type, ingredients[{moiety_id, salt_form, strength{value,unit,per}, role}], mapping_version, resolution{state, method, reason_code, candidates[]}, provenance[]`. Combination products are **always** expanded; a product without a verified expansion cannot enter a check (→ `UNVERIFIED_INPUT`).
**CheckResult (atomic, per check × ingredient/pair):** `check_id, state∈8, reason_code, severity?(for HIT), scope_applied{population,form,tele}, coverage{evaluated[], not_evaluated[{id,reason}]}, rule_ids+versions, evidence[{source,edition,date,locator}], data_snapshot_id, valid_until, computed_at, context_deps[{field,status}]`.
**Roll-up:** worst-first order for the banner: HIT > SOURCE_CONFLICT > {SERVICE_UNAVAILABLE, DATA_EXPIRED, NOT_CHECKED, UNVERIFIED_INPUT, PARTIAL_COVERAGE} > CHECKED_NO_HIT. A **finding with incomplete coverage** is two results: the atomic `HIT` plus an aggregate showing `PARTIAL_COVERAGE` with the uncovered list. `CHECKED_NO_HIT` renders as "No match in the scope checked: [list]" — wording linted so it cannot read as "safe". **[PROTO]** fixes: the prototype rolls up `OK` although interaction and allergy are `NOT_CHECKED` (F3).
**Provenance & uncertainty:** each claim → `{source, edition, date, locator, unit_id}`; each input field carries status; confidence from Scribe is shown but never used as truth.

### 5.3 Missing/conflicting/stale/unavailable
| Situation | State & behaviour |
|---|---|
| Patient field unknown/not collected | Rule needing it → `UNVERIFIED_INPUT`, reason `CONTEXT_MISSING:<field>`; doctor can supply, one prompt |
| Patient field stale | Same, reason `STALE_CONTEXT` |
| Rule set past `valid_until` | `DATA_EXPIRED` (computed, not simulated) |
| Two concurrent sources disagree | `SOURCE_CONFLICT`, both shown with dates (supersession is not conflict) |
| Rule DB/event store unreachable | `SERVICE_UNAVAILABLE`; no cached "clean" |
| No rule exists for ingredient | `NOT_CHECKED` with reason `NO_REVIEWED_RULE` |
| Evidence missing | Ladder descends, else abstain naming the missing slot |
| LLM unavailable | Extractive view, labelled; never silent |
| Offline | Valid snapshot → checks with "as of"; expired → `DATA_EXPIRED` |

### 5.4 Corrections, approvals, access, languages
- **One-tap correction** captures `{type: patient-data | drug-mapping | source-error | answer-quality, object ids, versions, free text (PHI-stripped), doctor id}`. *Patient-data* corrections route to the patient-context owner; *mapping/source* corrections enter review queues (two-key for rail content). Nothing becomes truth automatically; the doctor sees "pending review"; a tenant may keep a **local, labelled alias** that never changes canon (**D5/D9**).
- **Pending approvals** persist per doctor; on approve, a delta re-check runs against the newest snapshot; if any state worsens or a source is withdrawn, approval is blocked until acknowledged.
- **Access control:** role = doctor / clinic admin / reviewer / support; support has no PHI by default; break-glass is audited and time-boxed. **Shared machines:** per-user login, idle lock, no PHI cached unencrypted.
- **Languages/degraded operation:** see D13/D14; every degraded state shows a visible banner and is stamped in the audit event.

---

## S6 · What You Added
Ranked by severity. Format: **factor → where in current plan/prototype → consequence → severity → handling (link).**
| # | Factor | Where | Consequence | Sev | Handling |
|---|---|---|---|---|---|
| F1 | P02 "cumulative exposure totalled" conflicts with L12 | 01 P02 | A shipped feature would breach a fixed fence | Critical | Remove totalling; show strengths + cited maximum text (**D6**) |
| F2 | **[PROTO]** roll-up: `OK` event status while interaction/allergy `NOT_CHECKED`; "All supplied products had ingredient tokens" reads as completeness | `orchestrator.py`, `safety.py` | Unknown rendered as safe (L5), directly Gate 2 blocker | Critical | Roll-up rules and phrase lint (**§5.2**) |
| F3 | **[PROTO]** gate only checks any token hit; substring token matching; excerpt cut at 400 chars; `validated: True` hardcoded | `retrieval.py` | A confidently wrong or inapplicable "grounded" answer; exceptions/footnotes dropped | Critical | Class-slot gate, scope envelope, verifier (**D2, D3**) |
| F4 | **[PROTO]** population scope is a free-text string and the filter is optional (user-selected) | `retrieval.py`, `app.py` | Paediatric/pregnancy mismatch passes by default | Critical | Structured scope; mandatory filter from patient context (**D3**) |
| F5 | **[PROTO]** no fence/consequential classifier; keyword router sends "dose" to medication path | `orchestrator.py` | Dose, diagnosis, triage requests not refused | Critical | Fence classifier, R1/R2 (**§1.2**) |
| F6 | **[PROTO]** caller can supply ingredient tokens that override the graph (`name ⏐ a,b` syntax) | `orchestrator.py` | Bypasses L6; ingredient truth with no provenance | High | Remove override; only reviewed identity feeds checks (**D5**) |
| F7 | **[PROTO]** approval = session checkbox; audit has no actor, tenant column, versions, output hash; stores question text; in-memory ring buffer; tenant = UI label; service-role key in app | `app.py`, `audit.py`, schema | L8 unprovable; PHI leakage into audit | Critical | Hash-bound approval, chained audit, real tenancy (**D9–D11**) |
| F8 | "Byte-consistent replay" of LLM output | 03 Stage E | False guarantee | High | Redefine replay (**D10**) |
| F9 | Gate 1 "zero silent wrong mappings" without denominators | 03 Gate 1 | Zero observed ≠ zero true | High | Sample-size rule with upper bound, stratified (**S7-T1**) |
| F10 | Court stays and party-specific relief cannot be represented as simple scope | 01 P09/Stage B | "Banned" shown where stay protects a party, or vice versa | High | `scope.party`, stay events (**R8**) |
| F11 | Source rights: access ≠ index ≠ display; embeddings are derivative; WHO licence non-commercial | 02, 03 | Unlicensed corpus | High | Rights matrix, per-source flags (**S3.2**) |
| F12 | Review-throughput rule ("scope shrinks first") has no mechanism; single pharmacologist is a single point of failure | 03 §4 | Backlog → silent unreviewed content or stalled safety | High | Usage-weighted review queue; automatic capability demotion at queue threshold; second reviewer + conflict-of-interest log (**§7.3**) |
| F13 | Legal classification "mid-build"; final CDSCO MDSW guidance exists (Jul 2026); DPDP dates are near | 03 §4 | Stage C/F rails may be an unlicensed device | High | Memo is a gate before rail leaves supervised pilot (**S4-B**) |
| F14 | Multilingual/transliteration unspecified; no LASA registry | 02 | Silent wrong brand | High | Normaliser + LASA registry + per-language coverage (**D5, D13**) |
| F15 | Evaluation contamination: pilot corrections and AI-assisted development can leak into "held-out" sets | 03 gates | Inflated scores | High | Sealed hold-out, rotation, access logs (**S7**) |
| F16 | Erasure vs audit vs medical-record retention | 02 §5 | Legal conflict | High | Pseudonymised chain; retention by counsel (**R17**) |
| F17 | Alias dictionary exported upstream to bias recognition can push rare brands toward common ones | 03 Stage C | Feedback-loop mis-recognition | Medium-High | Candidate re-ranking only; measured in T1 |
| F18 | Alert fatigue handled only by "high severity"; unknown states multiply | 03 Stage E | Doctors ignore everything | Medium-High | Coverage banner, passive chips (**D12**) |
| F19 | Tenant overlay precedence "outranks national" | 03 Stage D | Hidden disagreement with national guidance | Medium-High | Side-by-side on conflict (**D1**) |
| F20 | Prompt injection through ingested PDFs/protocols, not only transcripts | 03 Stage E | Poisoned evidence | Medium | Data-only handling, schema output, verifier, ingest scan |
**Latency definition.** (a) *Medication-check path* (deterministic, snapshot-local): server p95 ≤ 2 s from Rx lines received to all states rendered. (b) *Reference path*: extractive evidence card with citations first-paint p95 ≤ 2 s; composed summary follows (target set in pilot, not assumed). Verified by synthetic probes per region and real-user timing.
**Stage-order challenges (no dates):** move cross-tenant negative suites and PHI-in-logs scan into Gate 1; legal classification memo and consent operations are prerequisites to Stage F; Gate 2 adds blockers for *stale/withdrawn source served* and *approval not hash-bound*.

---

## S7 · Validation & QA Plan

### 7.1 Metrics and denominators
- **Confidently wrong answer rate (CWR)** = served consequential answers with ≥1 incorrect, unsupported or inapplicable consequential claim ÷ all served consequential answers (abstentions excluded from the denominator, reported separately). Any *critical-severity* instance is individually release-blocking.
- **Useful supported answer rate (USAR)** = in-scope answerable questions answered with all consequential claims supported *and* applicable *and* rated useful by two clinicians ÷ in-scope answerable questions.
- **Appropriate abstention rate (AAR)** = abstentions on questions the key marks unanswerable-from-corpus ÷ all such questions. **Over-abstention rate** = abstentions on answerable questions ÷ answerable questions.
- **Claim support precision** = claims whose cited span supports them ÷ claims; **citation validity** = citations containing the claim ÷ citations; **applicability error rate** = served units whose scope envelope mismatches the case ÷ served units.
- Zero-count gates use an exact upper bound: with N independent cases and 0 observed critical failures, the 95% upper bound ≈ 3/N; each gate publishes N and the bound (e.g., N=300 → ≈1%).

### 7.2 Capability test plan
Format: **capability → test data/reference standard → method → pass criterion → evidence → validator.**
| Id | Capability | Data / reference | Method | Pass | Evidence | Validator |
|---|---|---|---|---|---|---|
| T1 | Drug mapping | Held-out brand strings (misspellings, transliteration, LASA, FDC variants) keyed by pharmacist + clinician | Run resolver; compare | **0 silent wrong mappings** over stratified N with published bound; 100% of truly ambiguous queued | Signed key, run report | QA runs; clinical pharmacologist owns key |
| T2 | Rail traps | Seeded duplicate/restricted-FDC/interaction/allergy/pregnancy traps authored by pharmacologist | Run; check state | 100% in-scope traps → HIT; 0 unknown-as-safe; all 8 states reachable | Trap matrix | QA + pharmacologist |
| T3 | Retrieval relevance | Question set with gold units | recall@k, MRR | Pre-registered threshold per class | Report | QA |
| T4 | Applicability | Questions with deliberately mismatched population/form/edition | Check served scope | 0 mismatched consequential units | Report | QA + specialty reviewer |
| T5 | Citation support / verifier | Labelled (claim, span) pairs incl. numbers, negations, units | Verifier vs labels | Zero critical misses; precision/recall reported | Labelled set | Clinical reviewers (labels), QA (run) |
| T6 | Conflict/supersession | Edition pairs and concurrent disagreements | Inspect cards | Superseded → current served; concurrent → side-by-side | Cards | Clinical lead |
| T7 | Fence | Adversarial prompts for dose/diagnosis/triage/patient advice | Run | 100% refuse/redirect | Run log | Clinical lead + counsel |
| T8 | Model/prompt/embedding change | Frozen regression suite | Full re-run | No gate regression; **no silent upgrade** | Diff report | QA; clinical sign-off for changes |
| T9 | Injection | Documents/transcripts with embedded instructions | Run | 0 behaviour changes | Report | Security + QA |
| T10 | Tenant isolation | Cross-tenant fuzz incl. cache/index | Run | 0 leaks | Report | Security |
| T11 | PHI hygiene | Seeded PHI through all paths | Scan logs/prompts/telemetry | 0 PHI in logs/prompts | Scan | Security |
| T12 | Audit replay | Random sample of outputs | Replay deterministic parts; compare stored text | Exact match; chain verifies | Replay report | QA |
| T13 | Degraded modes + latency | Fault injection per dependency; synthetic probes per region | Observe states; p95 | Visible state, no clean fallback; latency per S6 definition | Run log, dashboard | QA |
| T15 | Multilingual | Mixed-script lists per language | Mapping + gate tests | Per-language thresholds; failing language stays OFF | Matrix | Clinical + QA |
**Evaluation-set provenance:** (1) pharmacologist-authored traps; (2) de-identified pilot prescribing exports with consent, double-labelled; (3) logged real questions, de-identified; (4) adversarial/injection corpus; (5) multilingual lists from pilot clinics. A register records each case's origin, author, labeller(s), date and partition. **Held-out partition is sealed**: owned by clinical reviewers/QA, never visible to implementers or to AI coding agents; rotated by refresh; any test edited to pass = incident.

### 7.3 Operating at all-India scale without reviewing everything
- **Risk-tiering:** rail content, regulatory events and consequential units = 100% human review before publish (P05 retained). Background units sampled.
- **Daily (QA):** failed gates; override/dismissal rates; ambiguity-queue age; abstention and degraded-state counts; incident inbox; kill-switch status. **Weekly:** stratified production sample (all corrections, HIT overrides, low-margin retrievals, new-capability answers, plus a random sample sized to detect a 1% critical-error rate per stratum); source-feed diffs; usage-weighted reviewer queue. **Response targets:** P0 safety report acknowledged within 1 hour, capability disabled within 4 hours if reproduced (operating targets, not delivery dates).
- **Throughput rule operationalised:** if the reviewer queue exceeds its threshold, affected molecules/specialties **automatically drop to `NOT_CHECKED`/link-out** before any unreviewed content serves (F12).
- **Revalidation matrix:** model/prompt → T3–T9; embedding → T3–T5; source version → diff-driven tests + 100% review of changed consequential units; mapping change → T1+T2; rule change → T2 + pharmacologist re-sign; regulatory event → event-replay tests.

### 7.4 Who approves what
Engineering/QA proves *behaviour*; **clinical pharmacologist** approves rule content and keys; **specialty reviewers** approve specialty corpora; **counsel/regulatory affairs** approve legal posture and intended use; none of these is implied by a green test run.

---

## S8 · Doctor-Handover Checklist
**Item → required result → verification/evidence → responsible validator → blocker if open.** Status starts **OPEN**; none is pre-ticked. "Done" requires attached evidence.
| # | Area | Item | Required result | Evidence | Validator | Blocker? |
|---|---|---|---|---|---|---|
| 1 | Clinical | Rule content per molecule | Reviewer sign-off with rule ids/versions | Signed manifest | Clinical pharmacologist | **Yes** (molecule OFF) |
| 2 | Clinical | Specialty corpora | Specialty reviewer sign-off per specialty/population | Sign-offs | Specialty reviewers | Yes (specialty OFF) |
| 3 | Clinical | Intended-use and fence statement | Matches build; no dose/diagnosis/triage | Signed statement | Clinical lead | Yes |
| 4 | Legal | Device classification memo | Written position on CDS status/class | Memo | Counsel/regulatory affairs | **Yes** (rail beyond pilot) |
| 5 | Legal | DPDP/consent posture | Clinic consent staged; processor terms; breach runbook | Contracts, consent logs | Counsel | Yes |
| 6 | Legal | Telemedicine/IMC mapping | R9/R12 confirmed | Memo | Counsel | Yes for tele mode |
| 7 | Source | Rights per source | Matrix cleared for store/index/display | Licences/letters | Counsel | Yes (source OFF) |
| 8 | Source | Regulatory events loaded from gazette text | Each event has notification id, dates, scope, stay status | Event register | Regulatory reviewer | Yes |
| 9 | Data | Drug master coverage | Rx-weighted % of pilot prescriptions resolved; held-out key T1 passed | Key report with bound | Pharmacologist + QA | Yes |
| 10 | Data | Quarantine queue | No quarantined row serving as clean | Query report | QA | Yes |
| 11 | Data | Source versions pinned | Release manifest signed; changelog reviewed | Manifest | Clinical lead | Yes |
| 12 | Engineering | All 8 states reachable and rendered | Test T2/T13 pass | Run logs | QA | Yes |
| 13 | Engineering | Check path has no model call | Dependency + network lint | CI report | Engineering lead | Yes |
| 14 | Engineering | Tenant isolation | T10 passes | Report | Security | Yes |
| 15 | Engineering | Hash-bound approval + audit chain | T12 passes | Report | QA | Yes |
| 16 | Engineering | Scribe and patient-context contract tests | Green against stubs and real payload samples | CI | Integration owner | Yes |
| 17 | Engineering | Egress and PHI scans | T11 passes; provider contract terms in place | Reports | Security + counsel | Yes (composition OFF) |
| 18 | Operations | Latency/availability by region; support and correction channel live | Meets S6 definitions; test ticket handled | Dashboard, ticket | QA + support lead | Latency: no (publish actuals); support: yes |
| 19 | Operations | Incident runbook, rollback, kill-switches | Drill performed | Drill record | Ops lead | Yes |
| 20 | Operations | QA cadence staffed | Daily/weekly duties assigned; reviewer deputy named | Roster | QA lead | Yes |
| 22 | Org | Doctor instructions | One-page "what it does / does not do", state legend, override guidance | Document + doctor comprehension check | Clinical lead | Yes |
| 23 | Org | Consent staged physically in clinics | Evidence per clinic | Consent log | Ops/counsel | Yes |
| 24 | Org | **Coverage atlas published** | Per molecule/specialty/population/language: *validated* / *available-but-unvalidated (labelled)* / *off* | Atlas generated from flags | Handover owner + clinical lead | Yes |
**National availability ≠ validated coverage:** the product may be reachable nationwide, but only items marked *validated* in the atlas are presented as supported; the rest abstain or link out. "Everything off" is not handover; handover is a **declared, evidence-backed subset** with the residual bound from §7.1 attached.

---

## S9 · AI-Usage Note
1. I used an AI assistant to read the pack and prototype, draft the structure, and run web checks on Indian regulatory status; I reviewed all claims and left unverified matters marked as such.
2. **Overridden:** the pack's P02 "cumulative exposure totalled" — I removed it because totalling frequency × strength against a limit is a patient-specific dose calculation barred by the fixed fence (D6/F1); I also checked CDSCO's July 2026 final MDSW guidance rather than assuming it was still draft.
3. Most important remaining uncertainty: whether interaction and restricted-FDC alerts are legally medical-device CDS and in what class — only counsel/regulatory affairs can settle it (S4-B).
*(Edit this note to reflect your own actual AI use before submitting.)*
