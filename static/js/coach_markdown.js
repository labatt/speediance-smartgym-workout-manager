// Escape-first markdown renderer shared by the History and Assessment pages.
// Escapes HTML first, THEN applies a tiny markdown subset, so model output can never
// inject markup. Keep this the single source of truth for both pages.
function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function coachMarkdown(md) {
    const inline = s => escHtml(s)
        .replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+?)`/g, '<code class="bg-gray-800 px-1 rounded">$1</code>');

    // A GFM table: a header row, a |---|---| separator row, then body rows.
    const splitRow = line => {
        let s = line.trim();
        if (s.startsWith('|')) s = s.slice(1);
        if (s.endsWith('|')) s = s.slice(0, -1);
        return s.split('|').map(c => c.trim());
    };
    const isSep = line => line.includes('-') &&
        /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/.test(line);

    const lines = (md || '').split('\n');
    let html = '';
    // A STACK of open lists, so indented bullets actually nest. The old version matched
    // `^\s*[-*+]\s+` and threw the indent away, so every sub-bullet rendered at the same
    // level as its parent — which is why a section header and the exercises under it came
    // out as one flat list.
    const stack = [];            // [{ type: 'ul'|'ol', indent: <spaces> }]
    const openList = type =>
        `<${type} class="${type === 'ul' ? 'list-disc' : 'list-decimal'} ml-5 space-y-0.5 mb-1">`;
    const close = () => {
        while (stack.length) { html += `</li></${stack.pop().type}>`; }
    };
    const indentOf = line => line.match(/^[ \t]*/)[0].replace(/\t/g, '    ').length;
    const item = (type, indent, content) => {
        while (stack.length && indent < stack[stack.length - 1].indent) {
            html += `</li></${stack.pop().type}>`;
        }
        const top = stack[stack.length - 1];
        if (!top || indent > top.indent) {
            // Deeper: the parent <li> stays open and the nested list lives inside it.
            html += openList(type);
            stack.push({ type, indent });
        } else if (top.type !== type) {
            html += `</li></${stack.pop().type}>` + openList(type);
            stack.push({ type, indent });
        } else {
            html += '</li>';     // same level: close the previous item
        }
        html += `<li>${inline(content)}`;   // left open so a child list can nest inside
    };

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].replace(/\s+$/, '');
        const trimmed = line.trim();

        // Table: this line has pipes and the NEXT line is a separator row.
        if (trimmed.includes('|') && !isSep(line) &&
            i + 1 < lines.length && isSep(lines[i + 1])) {
            close();
            const headers = splitRow(line);
            let t = '<div class="overflow-x-auto my-2"><table class="w-full text-left border-collapse text-sm">';
            t += '<thead><tr>' + headers.map(h =>
                `<th class="border border-gray-700 px-2 py-1 bg-gray-800 font-semibold text-indigo-100">${inline(h)}</th>`
            ).join('') + '</tr></thead><tbody>';
            i += 2;  // consume header + separator
            while (i < lines.length && lines[i].includes('|') && lines[i].trim() && !isSep(lines[i])) {
                t += '<tr>' + splitRow(lines[i]).map(c =>
                    `<td class="border border-gray-700 px-2 py-1 align-top">${inline(c)}</td>`
                ).join('') + '</tr>';
                i++;
            }
            i--;  // step back so the for-loop's i++ lands on the next unconsumed line
            html += t + '</tbody></table></div>';
            continue;
        }

        if (!trimmed) { close(); continue; }
        if (/^---+$/.test(trimmed)) { close(); html += '<hr class="border-gray-700 my-2">'; continue; }
        let m;
        if ((m = line.match(/^(#{1,4})\s+(.*)$/))) { close(); html += `<div class="font-bold text-indigo-100 mt-2 mb-1">${inline(m[2])}</div>`; continue; }
        if ((m = line.match(/^[ \t]*[-*+]\s+(.*)$/))) { item('ul', indentOf(line), m[1]); continue; }
        if ((m = line.match(/^[ \t]*\d+\.\s+(.*)$/))) { item('ol', indentOf(line), m[1]); continue; }
        close();
        html += `<p class="mb-1.5">${inline(line)}</p>`;
    }
    close();
    return html;
}

// Node/CommonJS export so this can be unit-tested headlessly; harmless in the browser.
if (typeof module !== 'undefined' && module.exports) module.exports = { escHtml, coachMarkdown };
