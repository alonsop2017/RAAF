#!/usr/bin/env node
/**
 * Generate client summary report.
 * Creates a summary of all active requisitions for a client.
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
  WidthType,
  ShadingType
} from 'docx';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..');

// Load client info
function loadClientInfo(clientCode) {
  const configPath = join(PROJECT_ROOT, 'clients', clientCode, 'client_info.yaml');
  return yaml.load(readFileSync(configPath, 'utf8'));
}

// Load requisition config
function loadRequisitionConfig(clientCode, reqId) {
  const configPath = join(
    PROJECT_ROOT, 'clients', clientCode, 'requisitions', reqId, 'requisition.yaml'
  );
  if (!existsSync(configPath)) return null;
  return yaml.load(readFileSync(configPath, 'utf8'));
}

// List requisitions for a client
function listRequisitions(clientCode) {
  const reqDir = join(PROJECT_ROOT, 'clients', clientCode, 'requisitions');
  if (!existsSync(reqDir)) return [];
  return readdirSync(reqDir).filter(f => {
    const stat = existsSync(join(reqDir, f, 'requisition.yaml'));
    return stat;
  });
}

// Load assessments summary
function loadAssessmentsSummary(clientCode, reqId) {
  const assessmentsPath = join(
    PROJECT_ROOT, 'clients', clientCode, 'requisitions', reqId, 'assessments', 'individual'
  );

  if (!existsSync(assessmentsPath)) {
    return { total: 0, recommended: 0, topScore: 0 };
  }

  const files = readdirSync(assessmentsPath).filter(f => f.endsWith('_assessment.json'));
  let recommended = 0;
  let topScore = 0;

  for (const file of files) {
    try {
      const data = JSON.parse(readFileSync(join(assessmentsPath, file), 'utf8'));
      const rec = data.recommendation || '';
      if (rec === 'STRONG RECOMMEND' || rec === 'RECOMMEND') {
        recommended++;
      }
      const pct = data.percentage || 0;
      if (pct > topScore) topScore = pct;
    } catch (e) {
      // Skip invalid files
    }
  }

  return { total: files.length, recommended, topScore };
}

// Create header shading
function createHeaderShading() {
  return {
    type: ShadingType.SOLID,
    color: 'D5E8F0'
  };
}

// Generate client summary
function generateClientSummary(clientCode, options = {}) {
  const clientInfo = loadClientInfo(clientCode);
  const companyName = clientInfo.company_name || clientCode;
  const reportDate = new Date().toISOString().split('T')[0];

  // Get requisitions
  let requisitions = listRequisitions(clientCode);

  if (options.status) {
    requisitions = requisitions.filter(reqId => {
      const config = loadRequisitionConfig(clientCode, reqId);
      return config && config.status === options.status;
    });
  }

  const sections = [];

  // Title
  sections.push(
    new Paragraph({
      text: 'CLIENT RECRUITMENT SUMMARY',
      heading: HeadingLevel.HEADING_1,
      alignment: AlignmentType.CENTER,
      spacing: { before: 400, after: 200 }
    }),
    new Paragraph({
      text: companyName,
      heading: HeadingLevel.HEADING_2,
      alignment: AlignmentType.CENTER,
      spacing: { after: 100 }
    }),
    new Paragraph({
      text: `Report Date: ${reportDate}`,
      alignment: AlignmentType.CENTER,
      spacing: { after: 400 }
    }),
    new Paragraph({
      text: '═'.repeat(70),
      spacing: { after: 400 }
    })
  );

  // Summary stats
  let totalCandidates = 0;
  let totalRecommended = 0;
  const reqSummaries = [];

  for (const reqId of requisitions) {
    const config = loadRequisitionConfig(clientCode, reqId);
    if (!config) continue;

    const summary = loadAssessmentsSummary(clientCode, reqId);
    totalCandidates += summary.total;
    totalRecommended += summary.recommended;

    reqSummaries.push({
      reqId,
      title: config.job?.title || 'Unknown',
      status: config.status || 'unknown',
      assessed: summary.total,
      recommended: summary.recommended,
      topScore: summary.topScore,
      reportStatus: config.report_status || 'pending'
    });
  }

  sections.push(
    new Paragraph({
      text: 'Overview',
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 200, after: 100 }
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Total Active Requisitions: ', bold: true }),
        new TextRun(String(requisitions.length))
      ]
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Total Candidates Assessed: ', bold: true }),
        new TextRun(String(totalCandidates))
      ]
    }),
    new Paragraph({
      children: [
        new TextRun({ text: 'Total Recommended: ', bold: true }),
        new TextRun(String(totalRecommended))
      ],
      spacing: { after: 300 }
    })
  );

  // Requisition table
  sections.push(
    new Paragraph({
      text: 'Requisition Status',
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 200, after: 100 }
    })
  );

  const tableRows = [
    new TableRow({
      children: [
        new TableCell({ children: [new Paragraph({ text: 'Requisition', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Title', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Status', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Assessed', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Recommended', alignment: AlignmentType.CENTER })], shading: createHeaderShading() }),
        new TableCell({ children: [new Paragraph({ text: 'Report', alignment: AlignmentType.CENTER })], shading: createHeaderShading() })
      ]
    })
  ];

  for (const req of reqSummaries) {
    tableRows.push(
      new TableRow({
        children: [
          new TableCell({ children: [new Paragraph(req.reqId)] }),
          new TableCell({ children: [new Paragraph(req.title)] }),
          new TableCell({ children: [new Paragraph(req.status)] }),
          new TableCell({ children: [new Paragraph(String(req.assessed))] }),
          new TableCell({ children: [new Paragraph(String(req.recommended))] }),
          new TableCell({ children: [new Paragraph(req.reportStatus)] })
        ]
      })
    );
  }

  const table = new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: tableRows
  });

  sections.push(table);

  // Footer
  sections.push(
    new Paragraph({
      text: '─'.repeat(70),
      spacing: { before: 400, after: 200 }
    }),
    new Paragraph({
      text: 'Prepared by Archtekt Consulting Inc.',
      alignment: AlignmentType.CENTER
    }),
    new Paragraph({
      text: 'CONFIDENTIAL',
      alignment: AlignmentType.CENTER,
      spacing: { before: 100 }
    })
  );

  // Create document
  const doc = new Document({
    sections: [{
      properties: {},
      children: sections
    }]
  });

  return doc;
}

// Main function
async function main() {
  const args = process.argv.slice(2);

  let clientCode = null;
  let status = null;

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--client':
      case '-c':
        clientCode = args[++i];
        break;
      case '--status':
      case '-s':
        status = args[++i];
        break;
      case '--help':
      case '-h':
        console.log(`
Usage: node generate_client_summary.js --client <code> [options]

Options:
  --client, -c     Client code (required)
  --status, -s     Filter by status (active, on_hold, filled, cancelled)
  --help, -h       Show this help
        `);
        process.exit(0);
    }
  }

  if (!clientCode) {
    console.error('Error: --client is required');
    process.exit(1);
  }

  try {
    console.log(`Generating client summary for ${clientCode}...`);

    const doc = generateClientSummary(clientCode, { status });

    // Output path
    const dateStr = new Date().toISOString().split('T')[0].replace(/-/g, '').slice(2);
    const filename = `${clientCode}_summary_${dateStr}.docx`;
    const outputDir = join(PROJECT_ROOT, 'clients', clientCode);
    const outputPath = join(outputDir, filename);

    // Generate document
    const buffer = await Packer.toBuffer(doc);
    writeFileSync(outputPath, buffer);

    console.log(`✓ Summary generated: ${outputPath}`);

  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

main();
