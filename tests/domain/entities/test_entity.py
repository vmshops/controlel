from controlel.domain.entities.entity import Entity


def test_entity_creation():
    entity = Entity(name="Living Room", entity_type="zone")

    assert entity.name == "Living Room"
    assert entity.enabled is True
