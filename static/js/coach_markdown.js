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
    let html = '', listType = '';
    const close = () => { if (listType) { html += `</${listType}>`; listType = ''; } };

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
        if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
            if (listType !== 'ul') { close(); html += '<ul class="list-disc ml-5 space-y-0.5 mb-1">'; listType = 'ul'; }
            html += `<li>${inline(m[1])}</li>`; continue;
        }
        if ((m = line.match(/^\s*\d+\.\s+(.*)$/))) {
            if (listType !== 'ol') { close(); html += '<ol class="list-decimal ml-5 space-y-0.5 mb-1">'; listType = 'ol'; }
            html += `<li>${inline(m[1])}</li>`; continue;
        }
        close();
        html += `<p class="mb-1.5">${inline(line)}</p>`;
    }
    close();
    return html;
}

// Node/CommonJS export so this can be unit-tested headlessly; harmless in the browser.
if (typeof module !== 'undefined' && module.exports) module.exports = { escHtml, coachMarkdown };
