"""Optional YAML authoring boundary for simulation scenarios."""

from __future__ import annotations

from collections.abc import Mapping


def parse_yaml_mapping(source: str) -> object:
    """Parse YAML without making PyYAML a dependency of the runtime core."""

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - exercised by minimal installations
        raise RuntimeError("YAML scenario authoring requires the 'controlel[simulation]' extra") from error

    class UniqueKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
        pass

    def construct_unique_mapping(
        loader: UniqueKeySafeLoader,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> Mapping[object, object]:
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(f"duplicate YAML mapping key: {key}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueKeySafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_unique_mapping,
    )
    return yaml.load(source, Loader=UniqueKeySafeLoader)
