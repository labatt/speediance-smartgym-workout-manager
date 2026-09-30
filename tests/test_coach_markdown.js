// The renderer shared by the History and Assessment pages. Nesting is the point: the
// assessment lists muscle groups as bullets with exercises indented beneath them, and the
// old version threw the indent away so everything rendered flat.
const assert = require('assert');
const { coachMarkdown, escHtml } = require('../static/js/coach_markdown.js');

function test(name, fn) {
    try { fn(); console.log('  ok   ' + name); }
    catch (e) { console.log('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; }
}

console.log('coach_markdown');

test('indented bullets nest inside their parent item', () => {
    const html = coachMarkdown('- **Chest**\n  - Bench Press: steady.');
    assert.ok(html.includes('<li><strong>Chest</strong><ul'), 'child list must open inside the parent <li>');
    assert.ok(html.includes('<li>Bench Press: steady.</li></ul></li>'), 'and close before the parent does');
});

test('siblings at the same indent stay siblings', () => {
    const html = coachMarkdown('- one\n- two');
    assert.strictEqual((html.match(/<ul/g) || []).length, 1, 'one list, not two');
    assert.strictEqual((html.match(/<li>/g) || []).length, 2);
});

test('returning to the outer level closes the inner list', () => {
    const html = coachMarkdown('- **A**\n  - inner\n- **B**');
    assert.ok(html.includes('</ul></li><li><strong>B</strong>'), 'B is a sibling of A, not of inner');
});

test('every list is closed at the end', () => {
    const html = coachMarkdown('- **A**\n    - deep\n      - deeper');
    assert.strictEqual((html.match(/<ul/g) || []).length, (html.match(/<\/ul>/g) || []).length);
    assert.strictEqual((html.match(/<li>/g) || []).length, (html.match(/<\/li>/g) || []).length);
});

test('ordered and unordered lists do not merge', () => {
    const html = coachMarkdown('- bullet\n1. numbered');
    assert.ok(html.includes('<ol'), 'the numbered item opens its own list');
});

test('headings are headings, not list items', () => {
    const html = coachMarkdown('### Where you are strong\n- **Chest**');
    assert.ok(html.indexOf('Where you are strong') < html.indexOf('<ul'), 'heading precedes the list');
    assert.ok(!html.includes('<li>Where you are strong'));
});

test('markup in model output is escaped, not executed', () => {
    const html = coachMarkdown('- <img src=x onerror=alert(1)>');
    assert.ok(!html.includes('<img'), 'raw tags must not survive');
    assert.ok(html.includes('&lt;img'));
});

test('bold and code still render inside a nested item', () => {
    const html = coachMarkdown('- **A**\n  - **Row**: `60 lbs`');
    assert.ok(html.includes('<strong>Row</strong>'));
    assert.ok(html.includes('<code'));
});
