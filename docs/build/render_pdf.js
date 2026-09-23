#!/usr/bin/env node
// Print the guide's HTML to PDF through Chromium: HarfBuzz shapes the Arabic,
// and the page gets a footer with page numbers and a clickable outline.
//
//   node render_pdf.js <in.html> <out.pdf> [version]
//
// Needs playwright-chromium resolvable (NODE_PATH=<dir>/node_modules works).
const { chromium } = require('playwright-chromium');
const path = require('path');

(async () => {
  const [inHtml, outPdf, ver] = process.argv.slice(2);
  if (!inHtml || !outPdf) { console.error('usage: render_pdf.js <in.html> <out.pdf> [version]'); process.exit(2); }
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.goto('file://' + path.resolve(inHtml), { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    const footer = `<div style="width:100%;font-family:-apple-system,system-ui,sans-serif;font-size:7.5pt;
      color:#5b6475;padding:0 17mm;display:flex;justify-content:space-between;">
      <span>lesson-cut &middot; the complete guide${ver ? ' &middot; v' + ver : ''}</span>
      <span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`;
    await page.pdf({
      path: outPdf,
      preferCSSPageSize: true,
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: '<div></div>',
      footerTemplate: footer,
      outline: true,
      tagged: true,
    });
    console.log('pdf: ' + outPdf);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('PDF render failed: ' + e.message); process.exit(1); });
