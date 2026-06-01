from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


P4P_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(__file__).resolve().parent / "app"
PILOT_PACKAGE_ROOT = APP_ROOT / "pilot_node"
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Make this launcher module behave like the real pilot_node package so imports
# inside pilot_app.py can resolve pilot_node.config/routes/runtime.
sys.modules["pilot_node"] = sys.modules[__name__]
__path__ = [str(PILOT_PACKAGE_ROOT)]


def _load_app_module():
    module_path = Path(__file__).with_name("pilot_app.py")
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
