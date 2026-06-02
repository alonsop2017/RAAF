#!/usr/bin/env node
/**
 * Generate consolidated assessment report.
 * Outputs PDF by default; pass --format docx for legacy DOCX output.
 */

import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import yaml from 'js-yaml';
import { createRequire } from 'module';
const _require = createRequire(import.meta.url);
const _pdfmake   = _require('pdfmake');
const _pdfFonts  = _require('pdfmake/standard-fonts/Helvetica');
import {
  Document,
  Packer,
  Paragraph,
  Table,
  TableRow,
  TableCell,
  TextRun,
  HeadingLevel,
  AlignmentType,
  BorderStyle,
  WidthType,
  ShadingType,
  Header,
  Footer,
  PageNumber,
  NumberFormat
} from 'docx';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..');

// Load settings
function loadSettings() {
  const settingsPath = join(PROJECT_ROOT, 'config', 'settings.yaml');
  return yaml.load(readFileSync(settingsPath, 'utf8'));
}

// Load requisition config
function loadRequisitionConfig(clientCode, reqId) {
  const configPath = join(
    PROJECT_ROOT, 'clients', clientCode, 'requisitions', reqId, 'requisition.yaml'
  );
  return yaml.load(readFileSync(configPath, 'utf8'));
}

// Load client info
function loadClientInfo(clientCode) {
  const configPath = join(PROJECT_ROOT, 'clients', clientCode, 'client_info.yaml');
  return yaml.load(readFileSync(configPath, 'utf8'));
}

// Load all assessments for a requisition
function loadAssessments(clientCode, reqId, options = {}) {
  const batch = options.batch || null;
  const assessmentsPath = join(
    PROJECT_ROOT, 'clients', clientCode, 'requisitions', reqId, 'assessments', 'individual'
  );

  if (!existsSync(assessmentsPath)) {
    return [];
  }

  const files = readdirSync(assessmentsPath).filter(f => f.endsWith('_assessment.json'));
  const assessments = [];

  for (const file of files) {
    const data = JSON.parse(readFileSync(join(assessmentsPath, file), 'utf8'));

    // Filter by batch if specified
    if (batch && data.candidate?.batch !== batch) {
      continue;
    }

    // Filter by minimum score if specified
    if (options.minScore !== undefined && (data.percentage || 0) < options.minScore) {
      continue;
    }

    assessments.push(data);
  }

  // Sort by percentage descending
  assessments.sort((a, b) => (b.percentage || 0) - (a.percentage || 0));

  return assessments;
}

// Get recommendation color
function getRecommendationStyle(recommendation) {
  switch (recommendation) {
    case 'STRONG RECOMMEND':
      return { bold: true };
    case 'RECOMMEND':
      return { bold: true };
    case 'CONDITIONAL':
      return {};
    default:
      return { color: '666666' };
  }
}

// Create header shading
function createHeaderShading() {
  return {
    type: ShadingType.SOLID,
    color: 'D5E8F0'
  };
}

// Generate the report document
function generateReport(clientCode, reqId, options = {}) {
  const settings = loadSettings();
  const reqConfig = loadRequisitionConfig(clientCode, reqId);
  const clientInfo = loadClientInfo(clientCode);
  const assessments = loadAssessments(clientCode, reqId, options);

  if (assessments.length === 0) {
    throw new Error('No assessments found for this requisition');
  }

  const thresholds = reqConfig.assessment?.thresholds || settings.assessment.default_thresholds;
  const title = reqConfig.job?.title || 'Unknown Position';
  const companyName = clientInfo.company_name || clientCode;
  const reportDate = new Date().toISOString().split('T')[0];
  const topN = options.topCandidatesCount || 6;

  // Count by recommendation
  const counts = {
    'STRONG RECOMMEND': 0,
    'RECOMMEND': 0,
    'CONDITIONAL': 0,
    'DO NOT RECOMMEND': 0
  };

  for (const a of assessments) {
    const rec = a.recommendation || 'DO NOT RECOMMEND';
    if (counts.hasOwnProperty(rec)) {
      counts[rec]++;
    }
  }

  // Build document sections
  const sections = [];

  // Title page
  sections.push(
    new Paragraph({
      text: '═'.repeat(70),
      spacing: { before: 400, after: 200 }
    }),
    new Paragraph({
      text: 'CONSOLIDATED CANDIDATE ASSESSMENT REPORT',
      heading: HeadingLevel.HEADING_1,
      alignment: AlignmentType.CENTER,
      spacing: { before: 400, after: 400 }
    }),
    new Paragraph({
      text: '═'.repeat(70),
      spacing: { before: 200, after: 400 }
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Position: ', bold: true }),
        new TextRun(title)
      ],
      spacing: { before: 200 }
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Client: ', bold: true }),
        new TextRun(companyName)
      ]
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Requisition ID: ', bold: true }),
        new TextRun(reqId)
      ]
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Assessment Date: ', bold: true }),
        new TextRun(reportDate)
      ]
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Total Candidates: ', bold: true }),
        new TextRun(String(assessments.length))
      ],
      spacing: { after: 600 }
    }),
    new Paragraph({
      text: '─'.repeat(70),
      spacing: { before: 400, after: 200 }
    }),
    new Paragraph({
      text: 'CONFIDENTIAL',
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 100 }
    }),
    new Paragraph({
      text: `This document contains proprietary assessment information prepared by`,
      alignment: AlignmentType.CENTER,
      spacing: { before: 100 }
    }),
    new Paragraph({
      text: `Archtekt Consulting Inc. for the exclusive use of ${companyName}.`,
      alignment: AlignmentType.CENTER
    }),
    new Paragraph({
      text: 'Distribution or reproduction without authorization is prohibited.',
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 }
    }),
    new Paragraph({
      text: '═'.repeat(70),
      spacing: { before: 200 }
    })
  );

  // Page break
  sections.push(
    new Paragraph({ pageBreakBefore: true })
  );

  // Executive Summary
  sections.push(
    new Paragraph({
      text: 'Executive Summary',
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 400, after: 200 }
    }),
    new Paragraph({
      text: 'Recommendation Summary',
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 200, after: 100 }
    })
  );

  // Summary table
  const summaryTable = new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [
      new TableRow({
        children: [
          new TableCell({
            children: [new Paragraph({ text: 'Category', alignment: AlignmentType.CENTER })],
            shading: createHeaderShading()
          }),
          new TableCell({
            children: [new Paragraph({ text: 'Score Range', alignment: AlignmentType.CENTER })],
            shading: createHeaderShading()
          }),
          new TableCell({
            children: [new Paragraph({ text: 'Count', alignment: AlignmentType.CENTER })],
            shading: createHeaderShading()
          })
        ]
      }),
      new TableRow({
        children: [
          new TableCell({ children: [new Paragraph('STRONG RECOMMEND')] }),
          new TableCell({ children: [new Paragraph(`${thresholds.strong_recommend}%+`)] }),
          new TableCell({ children: [new Paragraph(String(counts['STRONG RECOMMEND']))] })
        ]
      }),
      new TableRow({
        children: [
          new TableCell({ children: [new Paragraph('RECOMMEND')] }),
          new TableCell({ children: [new Paragraph(`${thresholds.recommend}-${thresholds.strong_recommend - 1}%`)] }),
          new TableCell({ children: [new Paragraph(String(counts['RECOMMEND']))] })
        ]
      }),
      new TableRow({
        children: [
          new TableCell({ children: [new Paragraph('CONDITIONAL')] }),
          new TableCell({ children: [new Paragraph(`${thresholds.conditional}-${thresholds.recommend - 1}%`)] }),
          new TableCell({ children: [new Paragraph(String(counts['CONDITIONAL']))] })
        ]
      }),
      new TableRow({
        children: [
          new TableCell({ children: [new Paragraph('DO NOT RECOMMEND')] }),
          new TableCell({ children: [new Paragraph(`<${thresholds.conditional}%`)] }),
          new TableCell({ children: [new Paragraph(String(counts['DO NOT RECOMMEND']))] })
        ]
      })
    ]
  });

  sections.push(summaryTable);

  // Page break
  sections.push(
    new Paragraph({ pageBreakBefore: true })
  );

  // Complete Ranking Table
  sections.push(
    new Paragraph({
      text: 'Complete Candidate Ranking',
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 400, after: 200 }
    })
  );

  const rankingRows = [
    new TableRow({
      children: [
        new TableCell({ children: [new Paragraph({ text: 'Rank', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Candidate Name', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Score', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: '%', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Stability', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Recommendation', alignment: AlignmentType.CENTER })], shading: createHeaderShading() })
      ]
    })
  ];

  assessments.forEach((a, index) => {
    const name = a.candidate?.name || 'Unknown';
    const score = a.total_score || 0;
    const maxScore = a.max_score || 100;
    const percentage = a.percentage || 0;
    const stability = a.scores?.job_stability?.tenure_analysis?.risk_level || 'N/A';
    const recommendation = a.recommendation || 'PENDING';
    const style = getRecommendationStyle(recommendation);

    rankingRows.push(
      new TableRow({
        children: [
          new TableCell({ children: [new Paragraph(String(index + 1))] }),
          new TableCell({
            children: [new Paragraph({
              children: [new TextRun({ text: name, ...style })]
            })]
          }),
          new TableCell({ children: [new Paragraph(`${score}/${maxScore}`)] }),
          new TableCell({ children: [new Paragraph(`${percentage}%`)] }),
          new TableCell({ children: [new Paragraph(stability)] }),
          new TableCell({
            children: [new Paragraph({
              children: [new TextRun({ text: recommendation, ...style })]
            })]
          })
        ]
      })
    );
  });

  const rankingTable = new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: rankingRows
  });

  sections.push(rankingTable);

  // Page break
  sections.push(
    new Paragraph({ pageBreakBefore: true })
  );

  // Top Candidate Profiles (top 6)
  sections.push(
    new Paragraph({
      text: 'Top Candidate Profiles',
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 400, after: 200 }
    })
  );

  const topCandidates = assessments.slice(0, topN);

  topCandidates.forEach((a, index) => {
    const name = a.candidate?.name || 'Unknown';
    const batch = a.candidate?.batch || '';
    const score = a.total_score || 0;
    const maxScore = a.max_score || 100;
    const percentage = a.percentage || 0;
    const stability = a.scores?.job_stability?.tenure_analysis?.risk_level || 'N/A';
    const recommendation = a.recommendation || 'PENDING';
    const summary = a.summary || 'No summary available';
    const strengths = a.key_strengths || [];
    const concerns = a.areas_of_concern || [];

    sections.push(
      new Paragraph({
        text: `${index + 1}. ${name}`,
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 300, after: 100 }
      }),
      new Paragraph({
        children: [
          new TextRun({ text: 'Batch: ', bold: true }),
          new TextRun(batch || 'N/A'),
          new TextRun(' | '),
          new TextRun({ text: 'Score: ', bold: true }),
          new TextRun(`${score}/${maxScore} (${percentage}%)`),
          new TextRun(' | '),
          new TextRun({ text: 'Stability: ', bold: true }),
          new TextRun(stability)
        ],
        spacing: { after: 100 }
      }),
      new Paragraph({
        children: [
          new TextRun({ text: 'Recommendation: ', bold: true }),
          new TextRun({ text: recommendation, ...getRecommendationStyle(recommendation) })
        ],
        spacing: { after: 100 }
      }),
      new Paragraph({
        text: summary,
        spacing: { after: 100 }
      })
    );

    if (strengths.length > 0) {
      sections.push(
        new Paragraph({
          children: [new TextRun({ text: 'Key Strengths:', bold: true })],
          spacing: { before: 100 }
        })
      );
      strengths.forEach(s => {
        sections.push(new Paragraph({ text: `• ${s}`, indent: { left: 360 } }));
      });
    }

    if (concerns.length > 0) {
      sections.push(
        new Paragraph({
          children: [new TextRun({ text: 'Areas to Explore:', bold: true })],
          spacing: { before: 100 }
        })
      );
      concerns.forEach(c => {
        sections.push(new Paragraph({ text: `• ${c}`, indent: { left: 360 } }));
      });
    }

    sections.push(
      new Paragraph({ text: '─'.repeat(50), spacing: { before: 200, after: 200 } })
    );
  });

  // Signature block
  sections.push(
    new Paragraph({ pageBreakBefore: true }),
    new Paragraph({
      text: '─'.repeat(70),
      spacing: { before: 400, after: 200 }
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Report Prepared By:     ', bold: true }),
        new TextRun('____________________________')
      ],
      spacing: { before: 200 }
    }),
    new Paragraph({
      text: '                        Archtekt Consulting Inc.',
      spacing: { before: 100 }
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Date:                   ', bold: true }),
        new TextRun(reportDate)
      ],
      spacing: { before: 200 }
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Framework Reference:    ', bold: true }),
        new TextRun(`${reqConfig.assessment?.framework_template || 'base'} v${reqConfig.assessment?.framework_version || '1.0'}`)
      ],
      spacing: { before: 100 }
    }),
    new Paragraph({
      text: '─'.repeat(70),
      spacing: { before: 200 }
    })
  );

  // Create document
  const doc = new Document({
    sections: [{
      properties: {},
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              text: `CONFIDENTIAL - ${companyName}`,
              alignment: AlignmentType.RIGHT
            })
          ]
        })
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              children: [
                new TextRun(`Page `),
                new TextRun({
                  children: [PageNumber.CURRENT]
                }),
                new TextRun(` of `),
                new TextRun({
                  children: [PageNumber.TOTAL_PAGES]
                }),
                new TextRun(` | ${reqId}`)
              ],
              alignment: AlignmentType.CENTER
            })
          ]
        })
      },
      children: sections
    }]
  });

  return doc;
}

// ── PDF generation (pdfmake v0.3 — standard Helvetica fonts) ─────────────────

// Configure the pdfmake singleton once
_pdfmake.fonts = _pdfFonts;
_pdfmake.setLocalAccessPolicy(() => true);   // allow standard font lookups
_pdfmake.setUrlAccessPolicy(() => false);    // no remote resources

function recColor(rec) {
  if (rec === 'STRONG RECOMMEND') return '#1a5276';
  if (rec === 'RECOMMEND')        return '#1e8449';
  if (rec === 'CONDITIONAL')      return '#7d6608';
  return '#922b21';
}

async function generatePdfReport(clientCode, reqId, options = {}) {
    const settings    = loadSettings();
    const reqConfig   = loadRequisitionConfig(clientCode, reqId);
    const clientInfo  = loadClientInfo(clientCode);
    const assessments = loadAssessments(clientCode, reqId, options);

    if (assessments.length === 0) throw new Error('No assessments found for this requisition');

    const thresholds  = reqConfig.assessment?.thresholds || settings.assessment?.default_thresholds || {};
    const title       = reqConfig.job?.title || 'Unknown Position';
    const companyName = clientInfo.company_name || clientCode;
    const reportDate  = new Date().toISOString().split('T')[0];
    const topN        = options.topCandidatesCount || 6;

    const counts = { 'STRONG RECOMMEND': 0, 'RECOMMEND': 0, 'CONDITIONAL': 0, 'DO NOT RECOMMEND': 0 };
    for (const a of assessments) {
      const rec = a.recommendation || 'DO NOT RECOMMEND';
      if (Object.prototype.hasOwnProperty.call(counts, rec)) counts[rec]++;
    }

    const H_COLOR   = '#1a3a5c';
    const BODY_FONT = 9;
    const H1_SIZE   = 15;
    const H2_SIZE   = 11;

    function cell(text, opts = {}) {
      return { text: text ?? '', fontSize: opts.fontSize || BODY_FONT, bold: opts.bold || false,
               color: opts.color || '#000000', alignment: opts.align || 'left',
               margin: [3, 3, 3, 3], ...(opts.extra || {}) };
    }
    function hdrCell(text) {
      return { text, bold: true, fontSize: BODY_FONT, color: '#ffffff',
               fillColor: H_COLOR, alignment: 'center', margin: [3, 4, 3, 4] };
    }
    function sectionTitle(text) {
      return { text, fontSize: H2_SIZE, bold: true, color: H_COLOR,
               margin: [0, 14, 0, 6], decoration: 'underline' };
    }

    // Ranking table
    const rankRows = [[hdrCell('Rank'), hdrCell('Candidate'), hdrCell('Score'),
                       hdrCell('%'), hdrCell('Stability'), hdrCell('Recommendation')]];
    assessments.forEach((a, i) => {
      const name = a.candidate?.name || 'Unknown';
      const pct  = `${Math.round(a.percentage || 0)}%`;
      const stab = a.scores?.job_stability?.tenure_analysis?.risk_level || '—';
      const rec  = a.recommendation || 'DO NOT RECOMMEND';
      const bold = rec === 'STRONG RECOMMEND' || rec === 'RECOMMEND';
      rankRows.push([
        cell(String(i + 1),  { align: 'center', bold }),
        cell(name,           { bold }),
        cell(String(a.total_score ?? '—'), { align: 'center', bold }),
        cell(pct,            { align: 'center', bold }),
        cell(stab,           { align: 'center' }),
        cell(rec,            { bold, color: recColor(rec) })
      ]);
    });

    // Top candidate profiles
    const topProfiles  = [];
    const advanceable  = assessments.filter(a =>
      a.recommendation === 'STRONG RECOMMEND' || a.recommendation === 'RECOMMEND'
    ).slice(0, topN);

    for (const a of advanceable) {
      const name = a.candidate?.name || 'Unknown';
      topProfiles.push(
        { text: name, fontSize: 11, bold: true, color: H_COLOR, margin: [0, 8, 0, 2] },
        { text: `Score: ${a.total_score ?? '?'}/100 (${Math.round(a.percentage || 0)}%) — ${a.recommendation}`,
          fontSize: BODY_FONT, italics: true, margin: [0, 0, 0, 4] },
        { text: a.summary || '', fontSize: BODY_FONT, margin: [0, 0, 0, 4] }
      );
      if ((a.key_strengths || []).length)
        topProfiles.push({ text: 'Key Strengths:', bold: true, fontSize: BODY_FONT, margin: [0, 2, 0, 1] },
                         { ul: a.key_strengths, fontSize: BODY_FONT, margin: [8, 0, 0, 4] });
      if ((a.areas_of_concern || []).length)
        topProfiles.push({ text: 'Areas of Concern:', bold: true, fontSize: BODY_FONT, margin: [0, 2, 0, 1] },
                         { ul: a.areas_of_concern, fontSize: BODY_FONT, margin: [8, 0, 0, 4] });
    }

    // Recommendation lists
    const primary     = assessments.filter(a => a.recommendation === 'STRONG RECOMMEND' || a.recommendation === 'RECOMMEND');
    const conditional = assessments.filter(a => a.recommendation === 'CONDITIONAL');
    const dnr         = assessments.filter(a => a.recommendation === 'DO NOT RECOMMEND');
    const recList = list => list.length
      ? list.map(a => ({ text: `${a.candidate?.name || 'Unknown'} — ${Math.round(a.percentage || 0)}%`, fontSize: BODY_FONT }))
      : [{ text: 'None', fontSize: BODY_FONT, italics: true }];

    const docDef = {
      defaultStyle: { font: 'Helvetica', fontSize: BODY_FONT, lineHeight: 1.3 },
      pageMargins:  [50, 55, 50, 50],
      header: (page, pages) => ({
        columns: [
          { text: 'CONFIDENTIAL — FOR INTERNAL USE ONLY', fontSize: 7, color: '#999999', italics: true },
          { text: `Page ${page} of ${pages}`, alignment: 'right', fontSize: 7, color: '#999999' }
        ],
        margin: [50, 18, 50, 0]
      }),
      footer: {
        columns: [{ text: `Prepared by Archtekt Consulting Inc.  |  ${reportDate}`, fontSize: 7, color: '#999999' }],
        margin: [50, 0, 50, 18]
      },
      content: [
        { text: 'CONSOLIDATED CANDIDATE ASSESSMENT REPORT', fontSize: H1_SIZE, bold: true,
          alignment: 'center', color: H_COLOR, margin: [0, 0, 0, 8] },
        { text: title, fontSize: H2_SIZE + 1, alignment: 'center', margin: [0, 0, 0, 4] },
        { text: companyName, fontSize: 10, alignment: 'center', italics: true, margin: [0, 0, 0, 4] },
        { text: `Report Date: ${reportDate}   |   Total Candidates: ${assessments.length}`,
          fontSize: BODY_FONT, alignment: 'center', color: '#555555', margin: [0, 0, 0, 14] },
        { canvas: [{ type: 'line', x1: 0, y1: 0, x2: 495, y2: 0, lineWidth: 1.5, lineColor: H_COLOR }] },

        { text: '', margin: [0, 10] },
        sectionTitle('Executive Summary'),
        { table: { widths: ['*', '*', '*', '*'], body: [
            [hdrCell('Strong Recommend'), hdrCell('Recommend'), hdrCell('Conditional'), hdrCell('Do Not Recommend')],
            [
              cell(String(counts['STRONG RECOMMEND']), { align: 'center', bold: true, color: recColor('STRONG RECOMMEND'), fontSize: 14 }),
              cell(String(counts['RECOMMEND']),        { align: 'center', bold: true, color: recColor('RECOMMEND'),        fontSize: 14 }),
              cell(String(counts['CONDITIONAL']),       { align: 'center', bold: true, color: recColor('CONDITIONAL'),      fontSize: 14 }),
              cell(String(counts['DO NOT RECOMMEND']), { align: 'center', bold: true, color: recColor('DO NOT RECOMMEND'), fontSize: 14 })
            ]
          ]},
          layout: 'lightHorizontalLines', margin: [0, 0, 0, 12] },

        { text: '', pageBreak: 'before' },
        sectionTitle('Complete Candidate Rankings'),
        { table: { headerRows: 1, widths: [28, '*', 38, 32, 60, 100], body: rankRows },
          layout: { hLineColor: () => '#cccccc', vLineColor: () => '#cccccc' },
          margin: [0, 0, 0, 16] },

        ...(topProfiles.length ? [
          { text: '', pageBreak: 'before' },
          sectionTitle(`Top ${advanceable.length} Candidate Profile${advanceable.length !== 1 ? 's' : ''}`),
          ...topProfiles
        ] : []),

        { text: '', pageBreak: 'before' },
        sectionTitle('Hiring Recommendations'),
        { text: 'Primary Recommendations — Advance to Interview', bold: true, fontSize: 10, margin: [0, 4, 0, 4] },
        { ul: recList(primary), margin: [8, 0, 0, 10] },
        { text: 'Conditional Candidates', bold: true, fontSize: 10, margin: [0, 4, 0, 4] },
        { ul: recList(conditional), margin: [8, 0, 0, 10] },
        { text: 'Do Not Recommend', bold: true, fontSize: 10, margin: [0, 4, 0, 4] },
        { ul: recList(dnr), margin: [8, 0, 0, 10] },

        { canvas: [{ type: 'line', x1: 0, y1: 0, x2: 495, y2: 0, lineWidth: 0.5, lineColor: '#cccccc' }], margin: [0, 20, 0, 14] },
        { text: 'Evaluator Signature: _______________________________   Date: ___________', fontSize: BODY_FONT, margin: [0, 0, 0, 8] },
        { text: `Framework Reference: ${reqId}  |  Generated: ${reportDate}`, fontSize: 7, color: '#888888' }
      ]
    };

    const pdfDoc = _pdfmake.createPdf(docDef);
    return await pdfDoc.getBuffer();
}

// ── CLI ───────────────────────────────────────────────────────────────────────

// Main function
async function main() {
  const args = process.argv.slice(2);

  // Parse arguments
  let clientCode = null;
  let reqId = null;
  let outputType = 'draft';
  let batch = null;
  let minScore = undefined;
  let topCandidatesCount = 6;
  let format = 'pdf';  // default — use --format docx for legacy DOCX output

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--client':
      case '-c':
        clientCode = args[++i];
        break;
      case '--req':
      case '-r':
        reqId = args[++i];
        break;
      case '--output-type':
        outputType = args[++i];
        break;
      case '--batch':
      case '-b':
        batch = args[++i];
        break;
      case '--min-score':
        minScore = parseFloat(args[++i]);
        break;
      case '--top-candidates':
        topCandidatesCount = parseInt(args[++i], 10);
        break;
      case '--format':
        format = args[++i];   // 'pdf' or 'docx'
        break;
      case '--test':
        console.log('Test mode - would generate report');
        process.exit(0);
      case '--help':
      case '-h':
        console.log(`
Usage: node generate_report.js --client <code> --req <id> [options]

Options:
  --client, -c     Client code (required)
  --req, -r        Requisition ID (required)
  --output-type    Output type: draft or final (default: draft)
  --batch, -b      Specific batch to include
  --help, -h       Show this help
        `);
        process.exit(0);
    }
  }

  if (!clientCode || !reqId) {
    console.error('Error: --client and --req are required');
    process.exit(1);
  }

  try {
    console.log(`Generating report for ${reqId}...`);

    const usePdf = format !== 'docx';
    const dateStr = new Date().toISOString().split('T')[0].replace(/-/g, '').slice(2);
    const ext = usePdf ? 'pdf' : 'docx';
    const filename = `${reqId}_assessment_report_${dateStr}.${ext}`;
    const outputDir = join(
      PROJECT_ROOT, 'clients', clientCode, 'requisitions', reqId,
      'reports', outputType === 'final' ? 'final' : 'drafts'
    );

    if (!existsSync(outputDir)) {
      mkdirSync(outputDir, { recursive: true });
    }

    const outputPath = join(outputDir, filename);
    const opts = { batch, minScore, topCandidatesCount };

    let buffer;
    if (usePdf) {
      buffer = await generatePdfReport(clientCode, reqId, opts);
    } else {
      const doc = generateReport(clientCode, reqId, opts);
      buffer = await Packer.toBuffer(doc);
    }
    writeFileSync(outputPath, buffer);

    console.log(`✓ Report generated: ${outputPath}`);

  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

main();
