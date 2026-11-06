"""One-command demo: python run_demo.py   (dry-run over the fictitious sample data)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from invoice_bot.cli import main  # noqa: E402

raise SystemExit(main(["demo", *sys.argv[1:]]))
