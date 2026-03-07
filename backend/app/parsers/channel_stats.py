from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChannelStats:
    valid_count: int = 0
    invalid_count: int = 0
    min_val: float | None = None
    max_val: float | None = None
    sum_val: float = 0.0
    unique_values: set[int] = field(default_factory=set)

    def add(self, value: int | None) -> None:
        if value is None:
            self.invalid_count += 1
            return

        self.valid_count += 1
        self.sum_val += float(value)

        if self.min_val is None or value < self.min_val:
            self.min_val = float(value)
        if self.max_val is None or value > self.max_val:
            self.max_val = float(value)

        if len(self.unique_values) < 1000:
            self.unique_values.add(value)

    @property
    def mean_val(self) -> float | None:
        if self.valid_count == 0:
            return None
        return self.sum_val / self.valid_count

    @property
    def unique_count(self) -> int:
        return len(self.unique_values)


def compute_stats_for_matrix(values_matrix: list[list[int | None]]) -> list[ChannelStats]:
    if not values_matrix:
        return []

    channel_count = len(values_matrix[0])
    stats = [ChannelStats() for _ in range(channel_count)]

    for row in values_matrix:
        for idx, value in enumerate(row):
            stats[idx].add(value)

    return stats