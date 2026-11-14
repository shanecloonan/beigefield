"""RESTler-style producer–consumer inference.

Given the same typed methods, infer which call's outputs feed a later call
on a sibling contract. Edges are candidate sequences, not findings.
"""

from __future__ import annotations

from typing import Iterable

from eth_scanner.deep.blend.adapt.syzkaller import Method, PROTOCOL


def infer_edges(methods: Iterable[Method] | None = None) -> list[dict[str, str]]:
    pool = list(methods or PROTOCOL)
    producers: dict[str, list[Method]] = {}
    for method in pool:
        for resource in method.produces:
            producers.setdefault(resource, []).append(method)
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for consumer in pool:
        for resource in consumer.consumes:
            for producer in producers.get(resource, []):
                if producer.label == consumer.label:
                    continue
                key = (producer.label, consumer.label, resource)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "producer": producer.label,
                    "consumer": consumer.label,
                    "resource": resource,
                    "sibling": producer.contract != consumer.contract,
                })
    edges.sort(key=lambda row: (row["producer"], row["consumer"], row["resource"]))
    return edges
