// Tiny, safe Markdown renderer for the assistant's replies.
// We escape all HTML first, then apply a small set of formatting rules, so model
// output can never inject markup. Supports: headings, bold, italic, inline code,
// bullet/numbered lists, and paragraphs.
function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
}

export function renderMarkdown(src) {
  const lines = escapeHtml(src).split("\n");
  const html = [];
  let list = null; // "ul" | "ol" | null

  const closeList = () => {
    if (list) {
      html.push(`</${list}>`);
      list = null;
    }
  };

  for (let raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      closeList();
      continue;
    }
    let m;
    if ((m = line.match(/^#{1,6}\s+(.*)$/))) {
      closeList();
      const level = Math.min(line.match(/^#+/)[0].length, 6);
      html.push(`<h${level}>${inline(m[1])}</h${level}>`);
    } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
      if (list !== "ul") {
        closeList();
        list = "ul";
        html.push("<ul>");
      }
      html.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      if (list !== "ol") {
        closeList();
        list = "ol";
        html.push("<ol>");
      }
      html.push(`<li>${inline(m[1])}</li>`);
    } else {
      closeList();
      html.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  return html.join("");
}
