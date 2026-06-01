from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

P4P_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(__file__).resolve().parent / "app"
DEMO_PACKAGE_ROOT = APP_ROOT / "demo_node"

if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Make this launcher behave like the real demo_node package so imports inside
# demo_app.py still resolve when tests load this file under an arbitrary name.
sys.modules["demo_node"] = sys.modules[__name__]
__path__ = [str(DEMO_PACKAGE_ROOT)]


def _load_app_module():
    module_path = Path(__file__).with_name("demo_app.py")
    module_name = f"{__name__}_app"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_app = _load_app_module()
__all__ = getattr(_app, "__all__", [name for name in dir(_app) if not name.startswith("_")])

for _name in __all__:
    globals()[_name] = getattr(_app, _name)
