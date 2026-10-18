"""CI entry point: `python scripts/analyze_ai_tutor.py [--write] [--runtime runtime.json] [--json]` (npm run analyze-ai-tutor)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.ai_tutor.analyzer.cli import main  # noqa: E402

raise SystemExit(main())
