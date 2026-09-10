"""Fragrance Bot recipe engine.

Generates one unique, realistic, perfumery-safe DIY fragrance recipe per day
(deterministic per date), plus batch generation for seeding the recipe library.

Standard library only — no third-party dependencies, no network calls.
"""

from __future__ import annotations

__version__ = "0.1.0"

from datetime import date as _date

from .generator import RecipeGenerator, batch_generate, generate_recipe

__all__ = ["RecipeGenerator", "generate_recipe", "batch_generate", "__version__"]


def _demo() -> None:  # pragma: no cover - convenience only
    import json

    print(json.dumps(generate_recipe(_date.today()), indent=2))