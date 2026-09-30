"""Document assistants: user-attached Markdown knowledge bases with citations,
answered in their own chat surface (Phase 4B, `llm_fix_plan.md`).

Unlike the old custom-agent feature (removed in LLM-5), a document assistant has
no tools and cannot reach the generic assistant's prompt -- it answers only from
the documents attached to it, in `gridarena/llm/document_chat.py`.
"""

import re

# Chroma collection names are restricted to [a-zA-Z0-9._-], so a document
# assistant's collection can't use the "custom::{agent_id}" separator floated
# in the original design -- this prefix is the actual naming convention, and
# the one thing that structurally keeps a document assistant's content out of
# the generic assistant's retrieval path (see rag/retriever.py's guard, which
# checks against this exact constant).
DOCUMENT_COLLECTION_PREFIX = "custom_"

_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify_heading_path(heading_path: str) -> str:
    """Stable slug for a heading (or heading breadcrumb) used as a citation anchor.

    Computed in exactly one place and imported everywhere a heading needs a slug
    (ingest.py when recording each chunk's anchor; the source-viewer route when
    stamping `id` attributes on rendered headings) so the two can never
    independently drift out of sync -- a slug mismatch would silently break every
    citation link's "jump to this section" behaviour.
    """
    slug = _SLUG_NON_ALNUM_RE.sub("-", heading_path.lower()).strip("-")
    return slug or "section"
