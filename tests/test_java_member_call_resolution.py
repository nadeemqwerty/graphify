"""Gate-A: Java receiver-typed member-call resolution.

Deterministic, zero-AI regression gate for the Java member-call resolver
(``_resolve_java_member_calls``). It proves the resolver binds ``obj.method()``
calls to the method on the *declared receiver type* — not by name-uniqueness —
and expands interface/virtual dispatch to the sole implementor.

The prior graphify behaviour was name-unique-only: a ``method_invocation``
captured the callee name but never the receiver ``object``, so a callee name
that collided across >=2 classes was DROPPED, and a name with exactly one global
candidate MIS-BOUND ignoring the receiver's type. Here ``save`` collides
(``AssetRepository.save`` + ``JpaStore.save``), which is exactly the case the old
path got wrong.

Hard gates:
  1. ``AssetService.persist`` -> ``AssetRepository.save`` (field receiver, concrete type)
  2. ``IfaceService.doWrite`` -> ``JpaStore.save`` (interface receiver -> sole implementor)
  0 misbinds: doWrite must NOT bind to ``AssetRepository.save`` (wrong impl) nor to the
  abstract ``Store.save`` interface method.
"""

import pytest

from graphify.extract import extract

_FIXTURE = {
    "AssetController.java": """package com.example;
import org.springframework.web.bind.annotation.*;

@RestController
public class AssetController {
    private final AssetService service;
    public AssetController(AssetService service) { this.service = service; }

    @PostMapping("/assets/secure")
    public void createSecure(@RequestBody String body) {
        service.persist(body);
    }

    @PostMapping("/assets/open")
    public void createOpen(@RequestBody String body) {
        service.persist(body);
    }
}
""",
    "AssetService.java": """package com.example;
import org.springframework.stereotype.Service;

@Service
public class AssetService {
    private final AssetRepository repo;
    public AssetService(AssetRepository repo) { this.repo = repo; }
    public void persist(String body) {
        repo.save(body);
    }
}
""",
    "AssetRepository.java": """package com.example;
import org.springframework.stereotype.Repository;

@Repository
public class AssetRepository {
    public void save(String body) { /* writes to store */ }
}
""",
    "IfaceService.java": """package com.example;
import org.springframework.stereotype.Service;

@Service
public class IfaceService {
    private final Store store;   // declared as INTERFACE type
    public IfaceService(Store store) { this.store = store; }
    public void doWrite(String body) {
        store.save(body);        // virtual dispatch through Store
    }
}
""",
    "Store.java": """package com.example;
public interface Store {
    void save(String body);
}
""",
    "JpaStore.java": """package com.example;
import org.springframework.stereotype.Repository;

@Repository
public class JpaStore implements Store {
    public void save(String body) { /* real write */ }
}
""",
}


def _write_fixture(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name, body in _FIXTURE.items():
        (src / name).write_text(body, encoding="utf-8")
    return sorted(src.glob("*.java"))


def _call_edges(result):
    """Set of (source_id, target_id) for ``calls`` edges."""
    return {
        (e["source"], e["target"])
        for e in result["edges"]
        if (e.get("relation") or e.get("type")) == "calls"
    }


def _has(edges, src_sub, tgt_sub):
    return any(src_sub in s and tgt_sub in t for s, t in edges)


@pytest.fixture()
def java_calls(tmp_path):
    files = _write_fixture(tmp_path)
    return _call_edges(extract(files))


def test_field_receiver_binds_to_declared_type(java_calls):
    # HARD GATE 1: persist -> AssetRepository.save (field of concrete type)
    assert _has(java_calls, "persist", "assetrepository_assetrepository_save"), (
        f"missing persist->AssetRepository.save; calls={sorted(java_calls)}"
    )


def test_interface_receiver_expands_to_sole_implementor(java_calls):
    # HARD GATE 2: doWrite -> JpaStore.save (Store interface -> only implementor)
    assert _has(java_calls, "dowrite", "jpastore_jpastore_save"), (
        f"missing doWrite->JpaStore.save; calls={sorted(java_calls)}"
    )


def test_no_misbind_to_wrong_implementation(java_calls):
    # doWrite must NOT bind to AssetRepository.save (colliding name, wrong type)
    assert not _has(java_calls, "dowrite", "assetrepository_assetrepository_save"), (
        f"misbind doWrite->AssetRepository.save; calls={sorted(java_calls)}"
    )


def test_no_bind_to_abstract_interface_method(java_calls):
    # The abstract Store.save (no body) must not be a calls target when a concrete
    # sole implementor exists.
    assert not _has(java_calls, "dowrite", "store_store_save"), (
        f"misbind doWrite->Store.save (abstract); calls={sorted(java_calls)}"
    )


def test_colliding_name_does_not_drop_edges(java_calls):
    # Both save-callers resolve (old name-unique path would DROP both since save
    # collides across AssetRepository + JpaStore).
    assert _has(java_calls, "persist", "_save")
    assert _has(java_calls, "dowrite", "_save")
