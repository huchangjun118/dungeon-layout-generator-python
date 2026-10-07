"""Generator protocol shared by all algorithm versions."""
from __future__ import annotations

from typing import Protocol

from app.models import GenerationParams, Layout, Rect


class LayoutGenerator(Protocol):
    """A versioned layout generation algorithm."""

    version: str

    def generate(self, seed: int, params: GenerationParams) -> Layout:
        """Produce a full layout. Must be pure: same inputs -> same output."""
        ...

    def regenerate_region(
        self, layout: Layout, region: Rect
    ) -> Layout:
        """Regenerate only the tiles inside ``region`` of an existing layout.

        Content outside the region must be preserved byte-for-byte and the
        result must remain connected at the region boundary.
        """
        ...
