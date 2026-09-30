"""Minimal Markdown-to-HTML rendering for the document-assistant source viewer.

Not a general-purpose Markdown renderer: headings become real heading tags
carrying the `id` attribute citation links jump to, and everything else is
escaped and wrapped in paragraphs (no inline emphasis/links/code spans). That's
enough to make a source readable and its citation anchors functional without
adding a Markdown-rendering dependency -- see D5 in llm_fix_plan.md: Markdown
was chosen as the only accepted source format specifically so nothing else in
this feature needs a real parser either.

The heading walk here mirrors gridarena/llm/rag/embedder.py's split_into_sections
exactly (same nesting-stack rule), and slugify_heading_path is the same
function ingest.py used to compute each chunk's citation anchor -- so the `id`
rendered here for a given heading is always the same string a citation's anchor
points at. A test in tests/test_document_chat.py checks this directly.
"""

import html
import re
from typing import List, Tuple

from gridarena.llm.documents import slugify_heading_path

_HEADING_LINE_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


def render_markdown_with_anchors(text: str) -> str:
    lines = text.splitlines()
    html_parts: List[str] = []
    paragraph: List[str] = []
    stack: List[Tuple[int, str]] = []

    def flush_paragraph():
        if paragraph:
            escaped = html.escape("\n".join(paragraph)).replace("\n", "<br>")
            html_parts.append(f"<p>{escaped}</p>")
            paragraph.clear()

    for line in lines:
        m = _HEADING_LINE_RE.match(line)
        if m:
            flush_paragraph()
            level = len(m.group(1))
            title = m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            heading_path = " > ".join(t for _, t in stack)
            anchor = slugify_heading_path(heading_path)
            html_parts.append(f'<h{level} id="{anchor}">{html.escape(title)}</h{level}>')
        elif line.strip() == "":
            flush_paragraph()
        else:
            paragraph.append(line)

    flush_paragraph()
    return "\n".join(html_parts)
