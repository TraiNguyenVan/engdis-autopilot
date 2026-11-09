"""Unit module loader: dynamically loads unit handler or falls back to DefaultUnit."""

import importlib
import os
import re
from typing import Optional

from core.base_unit import BaseUnit, DefaultUnit


def normalize_course_slug(course_name: Optional[str]) -> str:
    """Normalize course name into directory slug (e.g. 'Advanced 3' -> 'a3')."""
    if not course_name:
        return "generic"

    c = course_name.strip().lower()
    # Shorthand conventions: Advanced 2 -> a2, Advanced 3 -> a3
    m = re.match(r"^(advanced|basic|intermediate)\s*(\d+)$", c)
    if m:
        prefix = m.group(1)[0]
        num = m.group(2)
        return f"{prefix}{num}"

    # General slugify
    slug = re.sub(r"[^a-z0-9]+", "_", c).strip("_")
    return slug or "generic"


def get_unit_handler(
    course_name: Optional[str],
    unit_index: int,
    unit_name: str = "",
) -> BaseUnit:
    """Find and instantiate unit handler for course and unit_index.

    Unit index is 0-based. Unit file naming convention is 1-based or 0-based:
    e.g. for unit_index=3 (Unit 4), tries:
      units.a3.u04, units.a3.u4, units.a3.u03, units.a3.u3
    """
    slug = normalize_course_slug(course_name)

    # 1-based unit number (what users/LMS call Unit 1..10)
    u_num_1based = unit_index + 1
    # 0-based unit number
    u_num_0based = unit_index

    candidate_modules = [
        f"units.{slug}.u{u_num_1based:02d}",
        f"units.{slug}.u{u_num_1based}",
        f"units.{slug}.unit_{u_num_1based:02d}",
        f"units.{slug}.unit_{u_num_1based}",
        f"units.{slug}.u{u_num_0based:02d}",
        f"units.{slug}.u{u_num_0based}",
    ]

    for mod_name in candidate_modules:
        try:
            mod = importlib.import_module(mod_name)
            # Find subclass of BaseUnit
            for attr in dir(mod):
                cls = getattr(mod, attr)
                if (
                    isinstance(cls, type)
                    and issubclass(cls, BaseUnit)
                    and cls not in (BaseUnit, DefaultUnit)
                ):
                    return cls(course=slug, unit_index=unit_index, unit_name=unit_name)
        except ModuleNotFoundError:
            continue
        except Exception as e:
            print(f"! Error loading unit module {mod_name}: {e}")

    # Fallback to default unit handler
    return DefaultUnit(course=slug, unit_index=unit_index, unit_name=unit_name)
