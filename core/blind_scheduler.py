"""BlindScheduler - Manages blind level progression in tournament mode."""

from typing import List


_NUM_BLIND_LEVELS = 10


class BlindScheduler:
    """Manages blind level progression and scheduling."""

    def __init__(self, big_blind: int, ante_enabled: bool = False) -> None:
        self.initial_big_blind = big_blind
        self.schedule: List[int] = [
            big_blind * (i + 1) for i in range(_NUM_BLIND_LEVELS)
        ]
        self.current_level = 0
        self.big_blind = big_blind
        self.ante_enabled = ante_enabled
        self.ante = (big_blind // 10) if ante_enabled else 0

    def escalate_blinds(self, hand_count: int, hands_per_level: int) -> str | None:
        """Escalate blinds if we've reached the required hand count.

        Args:
            hand_count: Current hand number
            hands_per_level: Number of hands per blind level

        Returns:
            Notification message if blinds escalated, None otherwise
        """
        if hand_count % hands_per_level == 0:
            next_level = self.current_level + 1
            if next_level < len(self.schedule):
                self.current_level = next_level
                self.big_blind = self.schedule[self.current_level]

                if self.ante_enabled:
                    self.ante = max(1, self.big_blind // 10)

                ante_info = f"  Ante: {self.ante}" if self.ante > 0 else ""
                return (
                    f"*** BLIND LEVEL UP — Blinds: {self.big_blind // 2}/{self.big_blind}"
                    f"{ante_info} ***"
                )

        return None

    def reset(self) -> None:
        """Reset to initial blind level."""
        self.current_level = 0
        self.big_blind = self.initial_big_blind
        self.ante = (self.big_blind // 10) if self.ante_enabled else 0

    @property
    def small_blind(self) -> int:
        """Return the current small blind amount."""
        return self.big_blind // 2

    @property
    def max_level(self) -> int:
        """Return the maximum blind level index."""
        return len(self.schedule) - 1
