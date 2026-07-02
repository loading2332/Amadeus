from __future__ import annotations

import importlib.util
import inspect

import amadeus
import amadeus.memory as public_memory
from amadeus.memory.engine import MemoryEngine


def _legacy_names() -> tuple[str, ...]:
    return (
        "Memory" + "IngestRequest",
        "Memory" + "Query",
        "Memory" + "Mutation",
        "Vector" + "MemoryEngine",
        "Vector" + "MemoryStore",
    )


def test_memory_engine_protocol_only_exposes_new_contract_methods() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(MemoryEngine)
        if inspect.isfunction(value) and not name.startswith("_")
    }

    assert public_methods == {
        "recall",
        "memorize",
        "forget",
        "undo_by_source",
        "build_context",
        "run_post_response",
    }


def test_public_packages_do_not_export_legacy_memory_contracts() -> None:
    legacy_names = _legacy_names()

    for name in legacy_names:
        assert not hasattr(public_memory, name)
        assert not hasattr(amadeus, name)
        assert name not in public_memory.__all__
        assert name not in amadeus.__all__


def test_legacy_vector_module_is_not_publicly_importable() -> None:
    assert importlib.util.find_spec("amadeus.memory." + "vector") is None
