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
    let html = '', listType = '';
    const close = () => { if (listType) { html += `</${listType}>`; listType = ''; } };
    for (const raw of (md || '').split('\n')) {
        const line = raw.replace(/\s+$/, '');
        if (!line.trim()) { close(); continue; }
        if (/^---+$/.test(line.trim())) { close(); html += '<hr class="border-gray-700 my-2">'; continue; }
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
