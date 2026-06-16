"""Response provenance/source-tag helpers.

Kept as a routing-facing shim so UI and controller code no longer import
provenance helpers from market_sources directly. The original implementations
remain in market_sources for backwards compatibility.
"""

from ..market_sources import (
    SOURCE_TAG_LABELS,
    SOURCE_TAG_ORDER,
    SOURCE_TAG_TOOLTIPS,
    build_response_source_tags,
    infer_response_source_tags,
    normalize_response_source_tags,
    source_tags_tooltip,
)

__all__ = [
    "SOURCE_TAG_LABELS",
    "SOURCE_TAG_ORDER",
    "SOURCE_TAG_TOOLTIPS",
    "build_response_source_tags",
    "infer_response_source_tags",
    "normalize_response_source_tags",
    "source_tags_tooltip",
]
