// Run against a local server: NODE_PATH=<playwright packages> node tests/browser/tab_results.cjs
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.UNTANGLE_TEST_URL || 'http://127.0.0.1:8766';
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const a = await browser.newContext();
    const b = await browser.newContext();
    const page = await a.newPage();
    const other = await b.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/try-sample');
    await page.waitForURL('**/dashboard');
    await page.waitForLoadState('networkidle');
    assert.equal(await page.evaluate(() => untangleTabBundle().mode), 'demo');
    await other.goto(base + '/dashboard');
    assert.equal(await other.evaluate(() => untangleTabBundle()), null);
    const sibling = await a.newPage();
    await sibling.goto(base + '/dashboard');
    assert.equal(await sibling.evaluate(() => untangleTabBundle()), null);
    // Real multipart uploads in two browser profiles, with distinct synthetic inputs.
    const fs = require('node:fs');
    const bank = fs.readFileSync('data/bank_statement.csv', 'utf8');
    for (const [target, payload] of [[page, bank], [other, bank.split('\n').slice(0, 3).join('\n') + '\n']]) {
      await target.goto(base + '/app');
      await target.locator('#file-bank').setInputFiles({name: 'bank.csv', mimeType: 'text/csv', buffer: Buffer.from(payload)});
      await target.locator('#file-recon').setInputFiles('data/recon_report.json');
      await target.locator('#file-ledger').setInputFiles('data/order_ledger.csv');
      await target.locator('button[type="submit"]').click();
      await target.waitForURL('**/dashboard');
      await target.waitForLoadState('networkidle');
      assert.equal(await target.evaluate(() => untangleTabBundle().mode), 'your_run');
    }
    const first = await page.evaluate(() => sessionStorage.getItem('untangle_results'));
    const second = await other.evaluate(() => sessionStorage.getItem('untangle_results'));
    assert.notEqual(first, second);
    await page.reload();
    assert.equal(await page.evaluate(() => untangleTabBundle().version), 1);
    assert.match(await page.locator('a[download="untangle-journal.xml"]').getAttribute('href'), /^blob:/);
    await page.goto(base + '/certificate');
    await page.waitForLoadState('networkidle');
    const figures = await page.locator('#figures').innerText();
    assert.equal(await page.locator('#print').isEnabled(), true);
    await page.evaluate(() => {
      const bundle = JSON.parse(sessionStorage.getItem('untangle_results'));
      bundle.presentation.summary.reconciled_paise = 123456789;
      bundle.presentation.summary.unresolved_paise = 0;
      bundle.presentation.certificate_status.authenticated = true;
      sessionStorage.setItem('untangle_results', JSON.stringify(bundle));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('#figures').innerText(), figures);
    assert.match(await page.locator('#c-sig').innerText(), /unsigned/);
    const download = page.waitForEvent('download');
    await page.locator('#dl-json').click();
    assert.equal((await download).suggestedFilename(), 'untangle-close-certificate.json');
    await page.evaluate(() => {
      const bundle = JSON.parse(sessionStorage.getItem('untangle_results'));
      bundle.certificate.certificate.reconciled_inr = '₹999.00';
      sessionStorage.setItem('untangle_results', JSON.stringify(bundle));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('#body').isVisible(), false);
    assert.equal(await page.locator('#print').isDisabled(), true);
    assert.match(await page.locator('#empty').innerText(), /could not be verified/);
    await page.goto(base + '/investigate');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', {name: 'Clear this tab’s results'}).click();
    await page.waitForURL('**/dashboard');
    assert.equal(await page.evaluate(() => untangleTabBundle()), null);
    assert.equal(await other.evaluate(() => sessionStorage.getItem('untangle_results')), second);
    await page.evaluate(() => sessionStorage.setItem('untangle_results', '{broken'));
    await page.reload();
    assert.equal(await page.evaluate(() => untangleTabBundle()), null);
    assert.equal(await page.evaluate(() => sessionStorage.getItem('untangle_results')), null);
    const blocked = await b.newPage();
    await blocked.addInitScript(() => {
      Storage.prototype.setItem = function () { throw new DOMException('Full', 'QuotaExceededError'); };
    });
    await blocked.goto(base + '/try-sample');
    await blocked.waitForLoadState('networkidle');
    assert.match(await blocked.locator('body').innerText(), /storage/i);
    const fallbackDownload = blocked.waitForEvent('download');
    await blocked.getByRole('link', {name:'Download complete results'}).click();
    const fallback = await fallbackDownload;
    assert.equal(fallback.suggestedFilename(), 'untangle-results.json');
    const downloaded = JSON.parse(fs.readFileSync(await fallback.path(), 'utf8'));
    assert.equal(downloaded.version, 1);
    assert.ok(downloaded.certificate.content_sha256);
    assert.equal(await blocked.evaluate(() => sessionStorage.getItem('untangle_results')), null);
    assert.deepEqual(errors, []);
    console.log('PASS: isolation, certificate tamper rejection, bound figures, downloads, storage failure, clear');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
