"""Direct, provider-free V2 smoke using a disposable project-local database."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory_v2 import MemoryV2Core, Status


with TemporaryDirectory(prefix="_v2_manual_", dir=Path(__file__).resolve().parent) as folder:
    db_path = Path(folder, "manual-test.db").resolve()
    assert db_path.is_relative_to(Path(__file__).resolve().parent)
    core = MemoryV2Core(db_path)

    x = core.create_scalar("user1", "harbor.signal_state", "idle", entity_id="beacon-x")
    y = core.create_scalar("user1", "harbor.signal_state", "active", entity_id="beacon-y")
    x_second = core.set_scalar("user1", "standby", memory_id=x.memory_id)
    x_third = core.set_scalar("user1", "ready", memory_id=x.memory_id)
    current_x = core.get_current_scalar("user1", memory_id=x.memory_id)
    previous_x = core.get_previous_scalar("user1", memory_id=x.memory_id)
    timeline_x = core.get_scalar_timeline("user1", memory_id=x.memory_id)
    current_y = core.get_current_scalar("user1", memory_id=y.memory_id)

    c1 = core.create_collection("user1", "aquatics.samples", entity_id="batch-a")
    c2 = core.create_collection("user1", "geology.samples", entity_id="batch-b")
    add_a = core.add_collection_member("user1", c1.collection_id, "sample-q", "sample Q")
    add_b = core.add_collection_member("user1", c2.collection_id, "sample-q", "sample Q")
    removed = core.remove_collection_member("user1", c1.collection_id, "sample-q")
    members_a = core.list_collection_members("user1", c1.collection_id)
    members_b = core.list_collection_members("user1", c2.collection_id)

    assert x.memory_id != y.memory_id and x.semantic_key == y.semantic_key
    assert (current_x.value, previous_x.value, current_y.value) == ("ready", "standby", "active")
    assert [version.value for version in timeline_x.timeline] == ["idle", "standby", "ready"]
    assert members_a.count == 0 and members_b.count == 1
    assert all(result.status == Status.APPLIED for result in
               (x, y, x_second, x_third, c1, c2, add_a, add_b, removed))

    print("X memory_id:", x.memory_id)
    print("X Current:", current_x.value)
    print("X Previous:", previous_x.value)
    print("X Timeline:", [version.value for version in timeline_x.timeline])
    print("Y memory_id:", y.memory_id)
    print("Y Current:", current_y.value)
    print("Semantic keys:", x.semantic_key, y.semantic_key)
    print("Collection A members:", [member.member_id for member in members_a.members])
    print("Collection B members:", [member.member_id for member in members_b.members])
    print("Mutation counts:", [result.mutation_count for result in
                               (x, y, x_second, x_third, c1, c2, add_a, add_b, removed)])
