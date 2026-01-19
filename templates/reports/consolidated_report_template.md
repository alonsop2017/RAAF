# Consolidated Report Template
# Structure and Guidelines for Assessment Reports

## Document Structure

### 1. Title Page

```
═══════════════════════════════════════════════════════════════════════════════

                    CONSOLIDATED CANDIDATE ASSESSMENT REPORT

═══════════════════════════════════════════════════════════════════════════════

Position:           [JOB TITLE]
Client:             [CLIENT COMPANY NAME]
Requisition ID:     [REQ-YYYY-NNN-ROLE]

Assessment Date:    [YYYY-MM-DD]
Total Candidates:   [N]

───────────────────────────────────────────────────────────────────────────────

                              CONFIDENTIAL

    This document contains proprietary assessment information prepared by
    Archtekt Consulting Inc. for the exclusive use of [CLIENT NAME].
    Distribution or reproduction without authorization is prohibited.

═══════════════════════════════════════════════════════════════════════════════
```

---

### 2. Executive Summary

```markdown
## Executive Summary

### Assessment Framework
This assessment evaluated candidates against [FRAMEWORK NAME] v[VERSION],
a [TOTAL POINTS]-point framework covering:
- Core Experience & Qualifications ([WEIGHT]%)
- Technical & Analytical Competencies ([WEIGHT]%)
- Relationship & Communication Skills ([WEIGHT]%)
- Strategic & Business Acumen ([WEIGHT]%)
- Job Stability Assessment ([WEIGHT]%)
- Cultural Fit & Soft Skills ([WEIGHT]%)

### Recommendation Thresholds
| Category | Score Range | Count |
|----------|-------------|-------|
| STRONG RECOMMEND | 85%+ | [N] |
| RECOMMEND | 70-84% | [N] |
| CONDITIONAL | 55-69% | [N] |
| DO NOT RECOMMEND | <55% | [N] |

### Summary
Of [TOTAL] candidates assessed, [N] are recommended for advancement to interviews.
```

---

### 3. Complete Candidate Ranking Table

```markdown
## Complete Candidate Ranking

| Rank | Candidate Name | Batch | Score | % | Stability | Recommendation |
|------|----------------|-------|-------|---|-----------|----------------|
| 1 | **[NAME]** | [BATCH] | [XX]/100 | [XX]% | [RISK] | **STRONG RECOMMEND** |
| 2 | **[NAME]** | [BATCH] | [XX]/100 | [XX]% | [RISK] | **RECOMMEND** |
| 3 | [NAME] | [BATCH] | [XX]/100 | [XX]% | [RISK] | CONDITIONAL |
| ... | ... | ... | ... | ... | ... | ... |

*Bold indicates candidates recommended for interview advancement*
```

---

### 4. Top Candidate Profiles

```markdown
## Top Candidate Profiles

### 1. [CANDIDATE NAME]
**Batch:** [BATCH_ID] | **Score:** [XX]/100 ([XX]%) | **Stability:** [RISK LEVEL]

[2-3 paragraph narrative summary highlighting:]
- Current/most recent role and key achievements
- Relevant experience alignment with requirements
- Notable quantified accomplishments
- Key differentiators

**Key Strengths:**
- [Strength 1 with evidence]
- [Strength 2 with evidence]
- [Strength 3 with evidence]

**Areas to Explore:**
- [Question/concern for interview]
- [Gap to probe]

---

### 2. [CANDIDATE NAME]
[Repeat format for top 6 candidates]
```

---

### 5. Hiring Recommendations

```markdown
## Hiring Recommendations

### Primary Recommendations (Advance to Interview)
The following candidates demonstrate strong alignment with role requirements
and are recommended for immediate interview consideration:

1. **[NAME]** - [One-line summary of why]
2. **[NAME]** - [One-line summary of why]
3. **[NAME]** - [One-line summary of why]

### Conditional Candidates (Consider if Primary Unavailable)
These candidates show potential but have notable gaps that should be explored:

1. **[NAME]** - [Gap/concern to address]
2. **[NAME]** - [Gap/concern to address]

### Not Recommended (Do Not Advance)
The following candidates do not meet minimum requirements:

**Common gaps observed:**
- [Gap pattern 1]
- [Gap pattern 2]
- [Gap pattern 3]

*Individual assessments available upon request.*
```

---

### 6. Batch Analysis (if multiple batches)

```markdown
## Batch Analysis

### Batch Summary
| Batch ID | Date | Candidates | Avg Score | Top Candidate |
|----------|------|------------|-----------|---------------|
| [BATCH_1] | [DATE] | [N] | [XX]% | [NAME] ([XX]%) |
| [BATCH_2] | [DATE] | [N] | [XX]% | [NAME] ([XX]%) |

### Observations
[Notes on batch quality trends, source effectiveness, etc.]
```

---

### 7. Signature Block

```markdown
───────────────────────────────────────────────────────────────────────────────

Report Prepared By:     ____________________________
                        [EVALUATOR NAME]
                        Archtekt Consulting Inc.

Date:                   [YYYY-MM-DD]

Framework Reference:    [FRAMEWORK_ID] v[VERSION]

───────────────────────────────────────────────────────────────────────────────
```

---

## Formatting Guidelines

### Fonts
- **Headings:** Arial 14pt Bold
- **Body:** Arial 11pt Regular
- **Tables:** Arial 10pt

### Colors
- Header background: #D5E8F0 (light blue)
- STRONG RECOMMEND: Bold text
- RECOMMEND: Bold text
- CONDITIONAL: Regular text
- DO NOT RECOMMEND: Regular text (gray if supported)

### Margins
- All margins: 1 inch

### Headers/Footers
- Header: "CONFIDENTIAL - [CLIENT NAME]"
- Footer: "Page X of Y | [REQUISITION_ID]"

---

## Data Mapping

When generating reports programmatically, map the following fields:

```javascript
// Report data structure
{
  client: {
    name: string,
    code: string
  },
  requisition: {
    id: string,
    title: string,
    framework_version: string
  },
  assessment_date: date,
  candidates: [
    {
      name: string,
      batch: string,
      score: number,
      max_score: number,
      percentage: number,
      stability_risk: string,
      recommendation: string,
      summary: string,
      strengths: string[],
      concerns: string[],
      interview_focus: string[]
    }
  ],
  thresholds: {
    strong_recommend: number,
    recommend: number,
    conditional: number
  },
  evaluator: {
    name: string,
    title: string
  }
}
```

---

## Quality Checklist

Before finalizing a report, verify:

- [ ] All candidate names spelled correctly
- [ ] Scores calculated accurately
- [ ] Ranking sorted by percentage (descending)
- [ ] Recommendation thresholds applied correctly
- [ ] Top candidate narratives are complete
- [ ] No Unicode characters that won't render in DOCX
- [ ] Confidentiality notice included
- [ ] Page numbers present
- [ ] Framework version referenced
- [ ] Date formats consistent
