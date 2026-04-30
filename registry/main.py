from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_app_module():
    module_path = Path(__file__).with_name("registry_app.py")
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
