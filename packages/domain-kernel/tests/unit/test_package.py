import importlib
import inspect
import pkgutil

import domain_kernel

_PRIVATE_MODULES = {"domain_kernel._validation"}


def _public_modules() -> list[str]:
    return [
        info.name
        for info in pkgutil.iter_modules(domain_kernel.__path__, prefix="domain_kernel.")
        if info.name not in _PRIVATE_MODULES
    ]


def test_importable() -> None:
    assert domain_kernel.__version__ == "0.1.0"


def test_every_exported_name_resolves_once() -> None:
    names = domain_kernel.__all__
    assert len(set(names)) == len(names)
    for name in names:
        assert hasattr(domain_kernel, name), name


def test_every_public_module_is_exported() -> None:
    modules = _public_modules()
    assert len(modules) == 23
    exported = set(domain_kernel.__all__)
    for module_name in modules:
        module = importlib.import_module(module_name)
        for name, value in vars(module).items():
            defined_here = (
                inspect.isclass(value) or inspect.isfunction(value)
            ) and value.__module__ == module_name
            if not name.startswith("_") and defined_here:
                assert name in exported, f"{module_name}.{name} is missing from __all__"
