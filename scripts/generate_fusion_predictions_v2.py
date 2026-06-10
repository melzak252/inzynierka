"""Run the repository-level Fusion v2 prediction generator.

Some deployment commands historically invoked this script from ``scripts``.
Execute the root script by path so all entrypoints share the same implementation.
"""

from pathlib import Path
import runpy


if __name__ == "__main__":
    script_path = Path(__file__).resolve().parents[1] / "generate_fusion_predictions_v2.py"
    runpy.run_path(str(script_path), run_name="__main__")
