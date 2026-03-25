from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
LIBS_DIR = PROJECT_ROOT.parents[1] / "libs"

if str(LIBS_DIR) not in sys.path:
    sys.path.insert(0, str(LIBS_DIR))


def _bootstrap_src_package() -> None:
    if "src" in sys.modules:
        return

    init_file = SRC_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "src",
        init_file,
        submodule_search_locations=[str(SRC_DIR)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 tui-service src 包: {SRC_DIR}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["src"] = module
    spec.loader.exec_module(module)


_bootstrap_src_package()
