from controlel.domain.value_objects.value_object import ValueObject


def test_value_object_creation():
    value = ValueObject(value=42)

    assert value.value == 42
