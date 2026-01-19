#!/usr/bin/env python3
"""
Generate RAAF Overview PDF document.
Creates a professional PDF for talent search company owners.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from pathlib import Path


def create_styles():
    """Create custom paragraph styles."""
    styles = getSampleStyleSheet()

    # Title style
    styles.add(ParagraphStyle(
        name='MainTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=6,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#1a365d')
    ))

    # Subtitle
    styles.add(ParagraphStyle(
        name='Subtitle',
        parent=styles['Normal'],
        fontSize=14,
        spaceAfter=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#4a5568')
    ))

    # Section heading
    styles.add(ParagraphStyle(
        name='SectionHeading',
        parent=styles['Heading1'],
        fontSize=16,
        spaceBefore=20,
        spaceAfter=12,
        textColor=colors.HexColor('#2c5282'),
        borderPadding=(0, 0, 5, 0)
    ))

    # Subsection heading
    styles.add(ParagraphStyle(
        name='SubHeading',
        parent=styles['Heading2'],
        fontSize=13,
        spaceBefore=15,
        spaceAfter=8,
        textColor=colors.HexColor('#2d3748')
    ))

    # Body text
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=8,
        alignment=TA_JUSTIFY,
        leading=14
    ))

    # Bullet point
    styles.add(ParagraphStyle(
        name='BulletText',
        parent=styles['Normal'],
        fontSize=10,
        leftIndent=20,
        spaceAfter=4,
        leading=13
    ))

    return styles


def create_table_style():
    """Create standard table style."""
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2d3748')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
    ])


def generate_pdf(output_path: str):
    """Generate the RAAF Overview PDF."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )

    styles = create_styles()
    story = []

    # Title Page
    story.append(Spacer(1, 1.5*inch))
    story.append(Paragraph(
        "Resume Assessment<br/>Automation Framework",
        styles['MainTitle']
    ))
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(
        "RAAF",
        ParagraphStyle(
            'BigTitle',
            parent=styles['MainTitle'],
            fontSize=48,
            textColor=colors.HexColor('#2c5282')
        )
    ))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph(
        "Executive Overview for Talent Search Company Owners",
        styles['Subtitle']
    ))
    story.append(Spacer(1, 1*inch))
    story.append(Paragraph(
        "Transform Your Candidate Assessment Process<br/>"
        "Deliver Professional Results in a Fraction of the Time",
        ParagraphStyle(
            'TagLine',
            parent=styles['Normal'],
            fontSize=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#4a5568'),
            leading=18
        )
    ))
    story.append(Spacer(1, 2*inch))
    story.append(Paragraph(
        "Archtekt Consulting Inc.<br/>Recruitment Services",
        ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#718096')
        )
    ))

    story.append(PageBreak())

    # What is RAAF?
    story.append(Paragraph("What is RAAF?", styles['SectionHeading']))
    story.append(Paragraph(
        "The <b>Resume Assessment Automation Framework (RAAF)</b> is a comprehensive "
        "software solution designed specifically for recruitment and talent search firms. "
        "It automates the labor-intensive process of evaluating candidate resumes against "
        "job requirements, producing professional assessment reports that help your clients "
        "make confident hiring decisions.",
        styles['CustomBody']
    ))
    story.append(Paragraph(
        "RAAF integrates directly with <b>PCRecruiter (PCR)</b>, enabling seamless candidate "
        "flow from job posting through Indeed to final assessment delivery—all while "
        "maintaining the high-quality, personalized service your clients expect.",
        styles['CustomBody']
    ))

    # The Problem
    story.append(Paragraph("The Problem RAAF Solves", styles['SectionHeading']))
    story.append(Paragraph("Current Challenges in Talent Search", styles['SubHeading']))

    challenges_data = [
        ['Challenge', 'Impact'],
        ['Manual resume review', 'Senior recruiters spend 6-8 hours per requisition'],
        ['Inconsistent evaluation', 'Different recruiters score candidates differently'],
        ['Delayed deliverables', 'Assessment reports take days to compile'],
        ['Scaling limitations', 'More requisitions require more staff'],
        ['Documentation gaps', 'Evaluation rationale often not captured'],
    ]
    challenges_table = Table(challenges_data, colWidths=[2.5*inch, 4*inch])
    challenges_table.setStyle(create_table_style())
    story.append(challenges_table)
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph(
        "RAAF transforms your assessment process from a manual, inconsistent effort into a "
        "<b>systematic, documented, and scalable operation</b> that delivers professional "
        "results in a fraction of the time.",
        styles['CustomBody']
    ))

    # Key Benefits
    story.append(Paragraph("Key Benefits", styles['SectionHeading']))

    story.append(Paragraph("1. Dramatic Time Savings", styles['SubHeading']))
    time_data = [
        ['Task', 'Manual Process', 'With RAAF'],
        ['Resume organization', '30 min/candidate', 'Automated'],
        ['Candidate scoring', '15-20 min/candidate', '2-3 min/candidate'],
        ['Report compilation', '2-3 hours', '5 minutes'],
        ['Total (30 candidates)', '12-15 hours', '2-3 hours'],
    ]
    time_table = Table(time_data, colWidths=[2.5*inch, 2*inch, 2*inch])
    time_table.setStyle(create_table_style())
    story.append(time_table)
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(
        "<b>Result:</b> Complete more requisitions with the same team, or deliver faster "
        "turnaround to clients.",
        styles['CustomBody']
    ))

    story.append(Paragraph("2. Consistent, Defensible Assessments", styles['SubHeading']))
    story.append(Paragraph("• <b>Standardized scoring frameworks</b> ensure every candidate is evaluated against the same criteria", styles['BulletText']))
    story.append(Paragraph("• <b>Evidence-based scoring</b> documents specific resume content supporting each score", styles['BulletText']))
    story.append(Paragraph("• <b>Audit trail</b> shows exactly how recommendations were determined", styles['BulletText']))
    story.append(Paragraph("• <b>Reduces bias</b> through structured evaluation methodology", styles['BulletText']))

    story.append(Paragraph("3. Professional Client Deliverables", styles['SubHeading']))
    story.append(Paragraph(
        "RAAF generates polished, comprehensive assessment reports including executive summaries, "
        "complete candidate rankings, detailed profiles for top candidates, interview focus areas, "
        "job stability analysis, and tiered hiring recommendations.",
        styles['CustomBody']
    ))

    story.append(Paragraph("4. Seamless ATS Integration", styles['SubHeading']))
    story.append(Paragraph("• Automatic candidate import from Indeed postings", styles['BulletText']))
    story.append(Paragraph("• Resume download without manual intervention", styles['BulletText']))
    story.append(Paragraph("• Assessment scores pushed back to candidate records", styles['BulletText']))
    story.append(Paragraph("• Pipeline status updates based on recommendations", styles['BulletText']))

    story.append(PageBreak())

    # PCRecruiter Integration Deep Dive
    story.append(Paragraph("PCRecruiter Integration", styles['SectionHeading']))
    story.append(Paragraph(
        "RAAF's deep integration with PCRecruiter eliminates manual data entry and ensures "
        "your ATS remains the single source of truth throughout the recruitment process.",
        styles['CustomBody']
    ))

    story.append(Paragraph("Streamlined Resume Intake", styles['SubHeading']))
    story.append(Paragraph(
        "The traditional resume intake process requires recruiters to manually download resumes "
        "from email notifications, rename files, organize them into folders, and track which "
        "candidates have been processed. RAAF automates this entire workflow:",
        styles['CustomBody']
    ))

    intake_data = [
        ['Step', 'Manual Process', 'RAAF Automated'],
        ['1. Candidate applies', 'Check Indeed email alerts', 'Auto-detected via PCR API'],
        ['2. Download resume', 'Open PCR, find candidate, download', 'Batch download all new resumes'],
        ['3. Rename files', 'Manually rename to standard format', 'Auto-normalized naming'],
        ['4. Organize', 'Create folders, move files', 'Auto-organized by requisition'],
        ['5. Track status', 'Update spreadsheet/notes', 'Manifest auto-generated'],
    ]
    intake_table = Table(intake_data, colWidths=[1.3*inch, 2.2*inch, 2.5*inch])
    intake_table.setStyle(create_table_style())
    story.append(intake_table)

    story.append(Spacer(1, 0.15*inch))
    story.append(Paragraph("Continuous Applicant Monitoring", styles['SubHeading']))
    story.append(Paragraph(
        "RAAF includes a <b>Watch Applicants</b> feature that continuously monitors PCRecruiter "
        "for new Indeed applicants. When candidates apply, RAAF automatically:",
        styles['CustomBody']
    ))
    story.append(Paragraph("• Detects new candidates within minutes of application", styles['BulletText']))
    story.append(Paragraph("• Downloads and normalizes their resumes", styles['BulletText']))
    story.append(Paragraph("• Adds them to the appropriate requisition folder", styles['BulletText']))
    story.append(Paragraph("• Updates the candidate manifest for tracking", styles['BulletText']))
    story.append(Paragraph("• Optionally triggers immediate assessment", styles['BulletText']))
    story.append(Paragraph(
        "This means your team can start each day with new candidates already organized and "
        "ready for assessment—no manual downloading or file management required.",
        styles['CustomBody']
    ))

    story.append(Paragraph("Bi-Directional Data Sync", styles['SubHeading']))
    story.append(Paragraph(
        "Unlike one-way integrations that only pull data, RAAF maintains a <b>bi-directional "
        "sync</b> with PCRecruiter, ensuring assessment results flow back into your ATS:",
        styles['CustomBody']
    ))

    sync_data = [
        ['Data Flow', 'What Syncs', 'When'],
        ['PCR → RAAF', 'Positions, candidates, resumes', 'On-demand or scheduled'],
        ['RAAF → PCR', 'Assessment scores (0-100)', 'After assessment complete'],
        ['RAAF → PCR', 'Recommendation tier', 'After assessment complete'],
        ['RAAF → PCR', 'Assessment notes/summary', 'After assessment complete'],
        ['RAAF → PCR', 'Pipeline status update', 'Based on recommendation'],
    ]
    sync_table = Table(sync_data, colWidths=[1.3*inch, 2.5*inch, 2.2*inch])
    sync_table.setStyle(create_table_style())
    story.append(sync_table)

    story.append(Spacer(1, 0.15*inch))
    story.append(Paragraph("Automatic Pipeline Management", styles['SubHeading']))
    story.append(Paragraph(
        "After assessments are complete, RAAF can automatically update candidate pipeline "
        "statuses in PCRecruiter based on their recommendation tier:",
        styles['CustomBody']
    ))

    pipeline_data = [
        ['Recommendation', 'PCR Pipeline Status', 'Next Action'],
        ['STRONG RECOMMEND', 'Interview Scheduled', 'Client notified, interview coordinated'],
        ['RECOMMEND', 'Interview Scheduled', 'Client notified, interview coordinated'],
        ['CONDITIONAL', 'On Hold', 'Available if top candidates decline'],
        ['DO NOT RECOMMEND', 'Not Selected', 'Rejection email triggered'],
    ]
    pipeline_table = Table(pipeline_data, colWidths=[1.8*inch, 1.8*inch, 2.4*inch])
    pipeline_table.setStyle(create_table_style())
    story.append(pipeline_table)

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(
        "Pipeline status mappings are fully configurable—customize them to match your firm's "
        "existing PCR workflow and status terminology.",
        styles['CustomBody']
    ))

    story.append(Paragraph("Assessment Notes in PCR", styles['SubHeading']))
    story.append(Paragraph(
        "When scores are pushed to PCRecruiter, RAAF also creates detailed assessment notes "
        "on each candidate record. This means anyone viewing the candidate in PCR can see:",
        styles['CustomBody']
    ))
    story.append(Paragraph("• Overall score and percentage", styles['BulletText']))
    story.append(Paragraph("• Recommendation tier with rationale", styles['BulletText']))
    story.append(Paragraph("• Key strengths identified", styles['BulletText']))
    story.append(Paragraph("• Areas of concern to probe in interview", styles['BulletText']))
    story.append(Paragraph("• Suggested interview focus areas", styles['BulletText']))
    story.append(Paragraph(
        "This ensures your entire team has visibility into assessment results without needing "
        "to access RAAF directly or search through report documents.",
        styles['CustomBody']
    ))

    story.append(PageBreak())

    # End-to-End Workflow
    story.append(Paragraph("End-to-End Workflow", styles['SectionHeading']))
    story.append(Paragraph(
        "Here's how RAAF transforms the complete recruitment cycle from job posting to client delivery:",
        styles['CustomBody']
    ))

    workflow_data = [
        ['Phase', 'Actions', 'Time'],
        ['1. Setup', 'Create position in PCR with job code INDML\nImport to RAAF, select framework template', '15 min'],
        ['2. Intake', 'Candidates apply via Indeed → auto-flow to PCR\nRAAF monitors and downloads resumes', 'Automated'],
        ['3. Organize', 'Resumes normalized and organized\nBatch created for assessment', '2 min'],
        ['4. Assess', 'Score each candidate against framework\nDocument evidence and rationale', '2-3 min each'],
        ['5. Report', 'Generate consolidated assessment report\nRank candidates, profile top performers', '5 min'],
        ['6. Sync', 'Push scores to PCR candidate records\nUpdate pipeline statuses automatically', '2 min'],
        ['7. Deliver', 'Send report to client\nTrack interview outcomes in PCR', '5 min'],
    ]
    workflow_table = Table(workflow_data, colWidths=[1*inch, 4*inch, 1*inch])
    workflow_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2d3748')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
    ]))
    story.append(workflow_table)

    story.append(Spacer(1, 0.15*inch))
    story.append(Paragraph(
        "<b>Total time for 30 candidates:</b> Under 3 hours from resume intake to client-ready report, "
        "compared to 12-15 hours with manual processes.",
        ParagraphStyle(
            'Highlight',
            parent=styles['CustomBody'],
            fontSize=10,
            textColor=colors.HexColor('#2c5282'),
            backColor=colors.HexColor('#ebf8ff'),
            borderPadding=10,
            leftIndent=10,
            rightIndent=10
        )
    ))

    story.append(PageBreak())

    # Assessment Framework
    story.append(Paragraph("Assessment Framework", styles['SectionHeading']))
    story.append(Paragraph(
        "RAAF uses a proven <b>100-point assessment framework</b> adaptable to any role:",
        styles['CustomBody']
    ))

    framework_data = [
        ['Category', 'Weight', 'What It Measures'],
        ['Core Experience', '25%', 'Years in role, industry alignment, education'],
        ['Technical Skills', '20%', 'Tools, systems, domain expertise'],
        ['Communication', '20%', 'Executive presence, presentation, collaboration'],
        ['Strategic Acumen', '15%', 'Business impact, planning, problem-solving'],
        ['Job Stability', '10%', 'Tenure patterns, flight risk assessment'],
        ['Cultural Fit', '10%', 'Adaptability, initiative, values alignment'],
    ]
    framework_table = Table(framework_data, colWidths=[1.8*inch, 0.8*inch, 3.9*inch])
    framework_table.setStyle(create_table_style())
    story.append(framework_table)

    story.append(Paragraph("Recommendation Tiers", styles['SubHeading']))
    tiers_data = [
        ['Tier', 'Score', 'Recommendation', 'Action'],
        ['1', '85%+', 'STRONG RECOMMEND', 'Advance to interview immediately'],
        ['2', '70-84%', 'RECOMMEND', 'Advance to interview'],
        ['3', '55-69%', 'CONDITIONAL', 'Consider if top candidates unavailable'],
        ['4', '<55%', 'DO NOT RECOMMEND', 'Do not advance'],
    ]
    tiers_table = Table(tiers_data, colWidths=[0.6*inch, 0.8*inch, 2*inch, 3.1*inch])
    tiers_table.setStyle(create_table_style())
    story.append(tiers_table)

    story.append(Paragraph("Job Stability Analysis", styles['SubHeading']))
    story.append(Paragraph(
        "RAAF includes proprietary job stability scoring that analyzes tenure patterns "
        "to help clients avoid costly mis-hires:",
        styles['CustomBody']
    ))
    stability_data = [
        ['Average Tenure', 'Risk Level', 'Score'],
        ['4+ years', 'Low Risk', '10/10'],
        ['3-4 years', 'Low-Medium', '8/10'],
        ['2-3 years', 'Medium', '6/10'],
        ['1.5-2 years', 'Medium-High', '4/10'],
        ['<1.5 years', 'High Risk', '0-2/10'],
    ]
    stability_table = Table(stability_data, colWidths=[2*inch, 2*inch, 1.5*inch])
    stability_table.setStyle(create_table_style())
    story.append(stability_table)

    # Role Templates
    story.append(Paragraph("Role-Specific Templates", styles['SectionHeading']))
    story.append(Paragraph(
        "RAAF includes pre-built assessment templates for common roles:",
        styles['CustomBody']
    ))
    story.append(Paragraph("• <b>SaaS Customer Success Manager</b> - Retention metrics, CRM proficiency, executive relationships", styles['BulletText']))
    story.append(Paragraph("• <b>SaaS Account Executive</b> - Quota attainment, sales methodology, deal complexity", styles['BulletText']))
    story.append(Paragraph("• <b>Construction Project Manager</b> - Safety certifications, project scale, subcontractor management", styles['BulletText']))
    story.append(Paragraph("• <b>Custom Templates</b> - Create frameworks for any role type with adjustable weights", styles['BulletText']))

    story.append(PageBreak())

    # ROI
    story.append(Paragraph("Return on Investment", styles['SectionHeading']))

    story.append(Paragraph("Cost-Benefit Analysis", styles['SubHeading']))
    roi_data = [
        ['Metric', 'Value'],
        ['Average requisition size', '30 candidates'],
        ['Recruiter cost', '$50/hour'],
        ['Current time per requisition', '12 hours'],
        ['RAAF time per requisition', '3 hours'],
        ['Time saved per requisition', '9 hours'],
        ['Cost saved per requisition', '$450'],
    ]
    roi_table = Table(roi_data, colWidths=[3*inch, 2*inch])
    roi_table.setStyle(create_table_style())
    story.append(roi_table)

    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("Annual Impact (50 requisitions/year)", styles['SubHeading']))
    annual_data = [
        ['Metric', 'Value'],
        ['Hours saved', '450 hours'],
        ['Cost saved', '$22,500'],
        ['Additional capacity', '37+ requisitions'],
    ]
    annual_table = Table(annual_data, colWidths=[3*inch, 2*inch])
    annual_table.setStyle(create_table_style())
    story.append(annual_table)

    story.append(Paragraph("Qualitative Benefits", styles['SubHeading']))
    story.append(Paragraph("• <b>Faster client delivery</b> → improved client satisfaction and retention", styles['BulletText']))
    story.append(Paragraph("• <b>Consistent quality</b> → stronger market reputation", styles['BulletText']))
    story.append(Paragraph("• <b>Documented process</b> → reduced liability and easier audits", styles['BulletText']))
    story.append(Paragraph("• <b>Scalable operations</b> → business growth without proportional cost increases", styles['BulletText']))

    # Conclusion
    story.append(Paragraph("Conclusion", styles['SectionHeading']))
    story.append(Paragraph(
        "RAAF transforms the candidate assessment process from a bottleneck into a competitive "
        "advantage. By automating the tedious aspects of resume review while maintaining the "
        "quality and personalization your clients expect, RAAF enables your firm to:",
        styles['CustomBody']
    ))
    story.append(Paragraph("• <b>Deliver faster</b> without sacrificing quality", styles['BulletText']))
    story.append(Paragraph("• <b>Scale operations</b> without proportional cost increases", styles['BulletText']))
    story.append(Paragraph("• <b>Produce professional reports</b> that differentiate your service", styles['BulletText']))
    story.append(Paragraph("• <b>Make data-driven recommendations</b> with documented rationale", styles['BulletText']))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(
        "The result is a more efficient operation, happier clients, and a stronger bottom line.",
        ParagraphStyle(
            'Conclusion',
            parent=styles['CustomBody'],
            fontSize=11,
            textColor=colors.HexColor('#2c5282'),
            alignment=TA_CENTER
        )
    ))

    # Next Steps
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Next Steps", styles['SectionHeading']))
    story.append(Paragraph("1. <b>Schedule a Demo</b> - See RAAF in action with your actual requisitions", styles['BulletText']))
    story.append(Paragraph("2. <b>Pilot Program</b> - Test RAAF on 2-3 requisitions at no risk", styles['BulletText']))
    story.append(Paragraph("3. <b>Full Implementation</b> - Deploy across your organization", styles['BulletText']))

    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph(
        "─" * 50,
        ParagraphStyle('Line', alignment=TA_CENTER, textColor=colors.HexColor('#cbd5e0'))
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(
        "<b>RAAF</b> - Resume Assessment Automation Framework<br/>"
        "Developed for Archtekt Consulting Inc.<br/>"
        "© 2025 All Rights Reserved",
        ParagraphStyle(
            'FooterFinal',
            parent=styles['Normal'],
            fontSize=9,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#718096'),
            leading=14
        )
    ))

    # Build PDF
    doc.build(story)
    print(f"PDF generated: {output_path}")


if __name__ == "__main__":
    import sys

    # Ensure docs directory exists
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)

    output_file = docs_dir / "RAAF_Overview.pdf"

    if len(sys.argv) > 1:
        output_file = Path(sys.argv[1])

    generate_pdf(str(output_file))
