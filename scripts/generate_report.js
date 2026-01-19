#!/usr/bin/env node
/**
 * Generate consolidated assessment report.
 * Creates DOCX reports from assessment data.
 */

import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import yaml from 'js-yaml';
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
function loadAssessments(clientCode, reqId, batch = null) {
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
  const assessments = loadAssessments(clientCode, reqId, options.batch);

  if (assessments.length === 0) {
    throw new Error('No assessments found for this requisition');
  }

  const thresholds = reqConfig.assessment?.thresholds || settings.assessment.default_thresholds;
  const title = reqConfig.job?.title || 'Unknown Position';
  const companyName = clientInfo.company_name || clientCode;
  const reportDate = new Date().toISOString().split('T')[0];

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

  const topCandidates = assessments.slice(0, 6);

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

// Main function
async function main() {
  const args = process.argv.slice(2);

  // Parse arguments
  let clientCode = null;
  let reqId = null;
  let outputType = 'draft';
  let batch = null;

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

    const doc = generateReport(clientCode, reqId, { batch });

    // Determine output path
    const dateStr = new Date().toISOString().split('T')[0].replace(/-/g, '').slice(2);
    const filename = `${reqId}_assessment_report_${dateStr}.docx`;
    const outputDir = join(
      PROJECT_ROOT, 'clients', clientCode, 'requisitions', reqId,
      'reports', outputType === 'final' ? 'final' : 'drafts'
    );

    // Ensure output directory exists
    if (!existsSync(outputDir)) {
      mkdirSync(outputDir, { recursive: true });
    }

    const outputPath = join(outputDir, filename);

    // Generate document
    const buffer = await Packer.toBuffer(doc);
    writeFileSync(outputPath, buffer);

    console.log(`✓ Report generated: ${outputPath}`);

  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

main();
