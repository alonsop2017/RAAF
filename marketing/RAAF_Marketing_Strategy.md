# RAAF Marketing Strategy
### Positioning RAAF (Resume Assessment Automation Framework) as a Standalone Product

**Prepared for:** Archtekt Consulting Inc.
**Document owner:** Alonso Perez
**Status:** Draft v1 — for internal review

---

## 1. Executive Summary

RAAF was built internally at Archtekt Consulting to solve a problem every recruiter has: too many resumes, too little consistent signal on which candidates are actually worth an interview. It has been running in production against real requisitions and real hires for months — it isn't a concept, it's a working system with a track record.

This document lays out a strategy for taking RAAF from an internal tool to an external product: who it's for, why they'd switch, how it's positioned against alternatives, and — just as importantly — what has to be true about the product before a go-to-market motion can succeed. The honest starting point: RAAF is functionally strong and validated by real usage, but it is currently architected as a single-tenant internal tool (one filesystem, one SQLite database, one Gmail inbox, one PCRecruiter account). Turning that into a sellable product is a real engineering investment, not a repositioning exercise. This strategy treats that as Phase 0, not a footnote.

---

## 2. Product Overview

**What RAAF does today:**

- Ingests candidate resumes from three channels — PCRecruiter (ATS) sync, automatic email monitoring, and manual upload — and normalizes them into a single pipeline.
- Generates a job-specific, weighted scoring framework from a job description using AI, rather than applying one generic rubric to every role.
- Scores every candidate against that framework across six weighted categories (core experience, technical/analytical skills, communication, strategic acumen, job stability, cultural fit), with each score backed by cited evidence from the resume text — not a black-box number.
- Calculates a distinct job-stability/tenure-risk score from employment history, a dimension most screening tools ignore entirely.
- Produces a consolidated, client-ready ranked report (DOCX) with recommendation tiers (Strong Recommend / Recommend / Conditional / Do Not Recommend) and per-candidate rationale.
- Syncs scores and pipeline status back into the ATS automatically, and can draft personalized interview invitations.
- Maintains a searchable repository of every candidate ever assessed, so a recruiter filling a similar role six months later can search past talent instead of starting from zero.
- Runs largely unattended: new PCR applicants are synced, downloaded, and assessed automatically every 5 minutes; emailed resumes are auto-ingested and matched to the right open requisition every 6 hours.

**What makes it credible as a product pitch:** it wasn't designed on a whiteboard for a demo. It was built to survive the mess of real recruiting operations — malformed filenames, duplicate submissions, candidates who apply to the same role twice under slightly different names, resumes that arrive as cover letters, PDFs that extract garbled text. That operational hardening is invisible in a demo but is exactly what separates a tool recruiters trust from one they abandon after week two.

---

## 3. Market Analysis

**The problem:** Recruiters and staffing agencies — especially independents and boutique firms without enterprise ATS budgets — spend a disproportionate amount of their time on resume triage rather than candidate relationships and closing. Screening quality is inconsistent between recruiters and between days (fatigue, bias, incomplete review), and there's rarely a defensible, evidence-backed rationale to hand a hiring manager when a candidate is rejected.

**Market context:**

- AI-assisted resume screening is an active and growing category, spanning enterprise ATS add-ons, standalone screening SaaS, and AI features bolted onto sourcing platforms.
- The segment RAAF is best positioned for is underserved by enterprise tools: independent recruiters, boutique/retained search firms, and small-to-mid staffing agencies who run high resume volume per requisition but don't have (or want) enterprise ATS platform budgets or IT overhead.
- Buyers in this segment are pragmatic and outcome-driven — they will adopt a tool the moment it demonstrably saves hours per requisition and improves placement quality, and will drop it the moment it adds friction or feels like a black box they can't explain to a client.

**Note for next revision:** this section should be backed by primary research (interviews with 8–10 recruiters/agency owners outside Archtekt) and a structured review of named competitors before this becomes a board-ready strategy. What's below is directional, not validated.

---

## 4. Competitive Landscape (Directional)

Rather than naming unverified competitors, it's more useful to map RAAF against **categories** of alternatives a prospective buyer is actually choosing between:

| Alternative | Why a buyer might pick it | Where RAAF wins |
|---|---|---|
| **Manual screening (status quo)** | No new tool, no cost, full control | Speed, consistency, and an evidence trail manual review can't match at volume |
| **ATS-native "AI match" scoring** | Already inside their existing ATS | Job-specific frameworks vs. generic keyword/semantic matching; transparent, cited scoring vs. an opaque match percentage; job-stability analysis most ATS tools skip entirely |
| **Standalone AI screening SaaS** | Purpose-built, may have slicker UI | Built and proven inside a real, high-volume agency workflow — not a lab product; native ATS pipeline sync rather than a screen you manually cross-reference |
| **Sourcing platforms with AI ranking bolted on** | Combines sourcing + screening | RAAF is not trying to replace sourcing — it's the assessment layer that plugs into whatever sourcing/ATS a firm already uses, which is a lower-friction sell |

**Action item:** before finalizing pricing and messaging, run a proper competitive teardown (Manatal, SeekOut, Humanly, HireVue's screening features, Loxo, and any PCRecruiter-marketplace AI add-ons specifically, since PCR is RAAF's proven integration). This strategy should not claim differentiation it hasn't actually verified against named products.

---

## 5. Value Proposition

**Primary value proposition:**
*"RAAF turns a stack of resumes into a ranked, evidence-backed shortlist — automatically, consistently, and in a format you can hand straight to a client or hiring manager."*

**Supporting pillars:**

1. **Evidence, not a black box.** Every score cites the specific resume language that justified it. Recruiters can defend a recommendation to a client instead of just reporting a number.
2. **Job-specific, not generic.** The scoring framework is generated from the actual job description, with adjustable category weights — a CSM req and a construction PM req are not scored the same way.
3. **It runs itself.** Candidates flow in from the ATS or inbox and are assessed automatically; the recruiter's job shifts from triage to judgment calls on the shortlist.
4. **Institutional memory.** Every past candidate is searchable against a new role. A firm's candidate pipeline compounds in value over time instead of resetting with every requisition.
5. **Built inside a real agency, under real load.** Not a proof of concept — validated against genuine placement outcomes.

---

## 6. Target Customer Segments (Ideal Customer Profile)

**Primary ICP — Phase 1 launch target:**
Independent recruiters and boutique retained-search/staffing firms (1–20 recruiters) who:
- Run meaningful resume volume per requisition (20+ candidates)
- Already use PCRecruiter, or a comparably lightweight ATS, or no real ATS at all
- Bill on a commission/placement-fee model, making "time saved per requisition" a direct, easy-to-quantify ROI conversation
- Are currently screening manually or with only their ATS's built-in keyword search

**Secondary ICP — Phase 2 expansion:**
- Mid-size staffing agencies (20–100 recruiters) with more formal reporting requirements to enterprise clients, where RAAF's consolidated client-ready reports are a distinct selling point
- Internal corporate TA teams running high-volume hourly/frontline hiring, where consistency and defensibility of screening decisions matters for compliance

**Explicitly not the near-term target:** large enterprise TA orgs requiring deep Workday/SuccessFactors integration, security review cycles, and procurement processes RAAF isn't built for yet. Chasing that segment before the product is ready would stall the whole motion.

---

## 7. Positioning & Messaging

**Positioning statement:**
For independent recruiters and boutique agencies who lose hours to manual resume screening, RAAF is an AI assessment layer that plugs into your existing ATS and inbox to produce ranked, evidence-backed candidate shortlists automatically — unlike generic AI "match scores," RAAF builds a framework specific to each role and shows its work.

**Core messages by audience:**

- **To the recruiter (end user):** "Stop reading resume #47 the same way you read resume #3. Let RAAF do the first pass, and spend your time on the candidates worth a phone call."
- **To the agency owner (economic buyer):** "Every hour a recruiter isn't screening is an hour they're selling, sourcing, or closing. RAAF turns screening from a cost center into a five-minute review step."
- **To the client/hiring manager (influencer):** "Every recommendation comes with the evidence behind it — not just a score."

**Proof points to develop:** time-per-requisition before/after, placement-quality metrics from Archtekt's own usage, and 2–3 anonymized case studies once available.

---

## 8. Pricing Strategy (Draft — needs validation)

Given the ICP bills per placement, a **hybrid model** likely lands best:

- **Per-seat SaaS subscription** (e.g., per active recruiter/month) as the base, since it's predictable for both sides and doesn't penalize a firm for high resume volume.
- **Usage-based tier or add-on** for firms with very high assessment volume, to capture value from high-throughput agencies without pricing out low-volume boutique firms.
- **Free/trial tier** scoped to a single active requisition, to let a prospect see a real ranked shortlist from their own job description before paying anything — this is the single highest-leverage conversion tool available, since RAAF's value is much easier to *see* than to describe.

Pricing needs competitive benchmarking (see Section 4) before numbers are attached to this document.

---

## 9. Go-to-Market Plan

**Phase 0 — Productization (prerequisite, not marketing)**
Before any external GTM spend: multi-tenant data isolation, self-serve onboarding (currently onboarding a client is a manual filesystem/config step), a real ATS integration story beyond PCRecruiter (or a clean CSV/manual-upload path for firms without PCR), and a security/privacy posture defensible to a buyer handling candidate PII. This phase has no marketing content associated with it, but no channel strategy below works until it's done.

**Phase 1 — Design partners & validation (0–2 months post-productization)**
- Recruit 3–5 design-partner agencies (ideally outside Archtekt's existing network, to pressure-test onboarding without hand-holding) at a steep discount in exchange for structured feedback and a usable case study.
- Goal: a credible "here's what changed for us" testimonial with real numbers, not projected ones.

**Phase 2 — Targeted launch (2–6 months)**
- **Content/inbound:** recruiter-facing content built around the evidence-based scoring angle and job-stability analysis — both are genuinely distinctive and demo well. Publish where recruiters already are (LinkedIn recruiter communities, staffing-industry newsletters/forums, PCRecruiter's own user community if accessible).
- **Partnership channel:** approach PCRecruiter (Main Sequence Technology) about marketplace/partner listing status — RAAF's deepest integration is already there, and it's a warm, high-intent channel to their existing customer base.
- **Direct outreach:** target boutique agencies matching the ICP directly, leading with the free single-requisition trial rather than a sales deck.
- **Referral loop:** design partners and early customers are the best source of second-wave leads in a small, networked industry like staffing — build a lightweight referral incentive early.

**Phase 3 — Expansion (6+ months)**
- Move toward the secondary ICP (mid-size agencies, internal TA teams) once the product has multi-ATS support and the reporting/compliance story is stronger.
- Revisit enterprise segment only once there's a credible security/procurement answer.

---

## 10. Success Metrics

**Product/GTM health:**
- Time-to-first-shortlist for a new customer (target: under 15 minutes from signup to a real ranked list on their own JD)
- Design-partner → paying-customer conversion rate
- Free-trial → paid conversion rate

**Customer value delivered:**
- Recruiter hours saved per requisition (self-reported + system-timestamp-derived)
- Shortlist-to-interview and shortlist-to-placement rates, vs. each customer's prior baseline

**Business:**
- MRR, logo count, net revenue retention, CAC payback period (once pricing is finalized)

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Product isn't actually multi-tenant-ready; rushing GTM before Phase 0 creates a bad first impression for early customers | Hold GTM spend until Phase 0 is genuinely done — protect the "built and battle-tested" narrative by not launching something half-finished |
| AI scoring errors or bias erode trust in a category where trust is the entire value proposition | Keep the evidence-citation design (already built) front and center in messaging; keep a human-in-the-loop review/reassess step as a permanent feature, not a stopgap |
| Candidate PII handling under scrutiny once selling outside a single trusted internal team | Get a real security/privacy review done before Phase 1 design partners, not after |
| Competing against well-funded AI screening SaaS with bigger marketing budgets | Win on category specificity (agency/independent-recruiter workflow, ATS-agnostic assessment layer) rather than competing head-on for the same enterprise buyer |
| PCRecruiter dependency limits addressable market | Prioritize a second ATS integration or a strong ATS-agnostic manual/CSV path in Phase 0/1 roadmap |

---

## 12. Immediate Next Steps

1. Validate this strategy's assumptions with 8–10 outside-agency interviews before committing engineering time to Phase 0.
2. Scope Phase 0 productization work as a concrete engineering roadmap with estimates (multi-tenancy, onboarding, security review).
3. Run the competitive teardown named in Section 4.
4. Identify 3–5 candidate design partners from outside Archtekt's existing network.
5. Draft the free-trial "single requisition" flow as the centerpiece of the Phase 2 launch motion.

---

*This is a living strategy document — update it as Phase 0 scoping, competitive research, and design-partner feedback land.*
