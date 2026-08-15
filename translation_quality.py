#!/usr/bin/env python3
"""Kompatibilitätsstarter für die integrierte Qualitätsprüfung."""
from studio.translation_quality import *  # noqa: F401,F403
from studio.translation_quality import main

if __name__ == "__main__":
    raise SystemExit(main())
