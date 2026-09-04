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
    const download = page.waitForEvent('download');
    await page.locator('#dl-json').click();
    assert.equal((await download).suggestedFilename(), 'untangle-close-certificate.json');
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
    assert.equal(await blocked.evaluate(() => sessionStorage.getItem('untangle_results')), null);
    assert.deepEqual(errors, []);
    console.log('PASS: independent browsers/tabs, refresh, downloads, navigation, clear, corrupt storage');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
