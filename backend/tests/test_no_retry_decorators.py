"""Verify that no provider method uses tenacity @retry decorators.

Failures should be surfaced to the user immediately — never silently retried.
A retry would multiply API costs and hide transient errors.
"""
import importlib
import inspect
import pkgutil

import app.providers as providers_pkg


def _all_provider_modules():
    """Yield every module inside app.providers (non-recursive)."""
    for info in pkgutil.iter_modules(providers_pkg.__path__, providers_pkg.__name__ + "."):
        yield importlib.import_module(info.name)


def _all_public_methods(cls):
    """Yield (name, method) for every non-dunder method on *cls*."""
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        yield name, method


def test_no_tenacity_imports():
    """No provider module should import tenacity."""
    for mod in _all_provider_modules():
        source = inspect.getsource(mod)
        assert "from tenacity" not in source and "import tenacity" not in source, (
            f"{mod.__name__} still imports tenacity — remove the import"
        )


def test_no_retry_decorators_on_methods():
    """No provider class method should be wrapped by @retry."""
    for mod in _all_provider_modules():
        for _, cls in inspect.getmembers(mod, predicate=inspect.isclass):
            if not cls.__module__.startswith("app.providers"):
                continue
            for method_name, method in _all_public_methods(cls):
                # tenacity wraps functions and sets a `retry` attribute
                assert not hasattr(method, "retry"), (
                    f"{cls.__name__}.{method_name} in {mod.__name__} "
                    "is wrapped with @retry — remove the decorator"
                )


def test_no_retry_string_in_source():
    """Catch any @retry decorator that might slip through attribute checks."""
    import re

    decorator_pattern = re.compile(r"^\s*@retry\b", re.MULTILINE)
    for mod in _all_provider_modules():
        source = inspect.getsource(mod)
        match = decorator_pattern.search(source)
        assert match is None, (
            f"{mod.__name__} contains @retry decorator at "
            f"line ~{source[:match.start()].count(chr(10)) + 1}"
        )
