"""ShowdownHandler - Handles poker showdown logic, hand evaluation, and pot distribution."""

from typing import List, Dict, Tuple, TYPE_CHECKING

from core.evaluator import HandEvaluator, HandRank

if TYPE_CHECKING:
    from core.player import Player
    from core.betting import PotManager


class ShowdownResult:
    """Stores the result of a showdown."""

    def __init__(self) -> None:
        self.winners: List[str] = []
        self.winnings: Dict[str, int] = {}
        self.hand_scores: Dict[str, tuple] = {}

    def record_win(self, player_id: str, amount: int) -> None:
        """Record a win for a player."""
        self.winners.append(player_id)
        self.winnings[player_id] = self.winnings.get(player_id, 0) + amount

    def add_hand_score(self, player_id: str, score: tuple, hand_name: str) -> None:
        """Store hand evaluation score for a player."""
        self.hand_scores[player_id] = score


class ShowdownHandler:
    """Handles showdown logic: hand evaluation and pot distribution."""

    def __init__(self, short_deck: bool = False) -> None:
        self.short_deck = short_deck

    def evaluate_hands(
        self,
        players: List['Player'],
        community_cards: list,
    ) -> Dict[str, Tuple[tuple, str, str]]:
        """Evaluate hands for all active players and return scores.

        Returns:
            Dict mapping player_id to (score, hand_name, best_hand_cards) tuple.
        """
        active_players = [p for p in players if p.is_active]
        scores: Dict[str, Tuple[tuple, str, str]] = {}

        for p in active_players:
            score, best_hand = HandEvaluator.evaluate(
                p.hole_cards, community_cards, short_deck=self.short_deck
            )
            hand_name = HandRank.to_string(score[0], short_deck=self.short_deck)
            scores[p.player_id] = (score, hand_name, str(best_hand))

        return scores

    def distribute_pots(
        self,
        pots: list,
        players: List['Player'],
        scores: Dict[str, Tuple[tuple, str]],
        dealer_idx: int,
        num_players: int,
    ) -> ShowdownResult:
        """Distribute all pots to winners.

        Args:
            pots: List of Pot objects from PotManager
            players: All players in the game
            scores: Hand scores from evaluate_hands()
            dealer_idx: Current dealer index
            num_players: Total number of players

        Returns:
            ShowdownResult with winners and winnings
        """
        result = ShowdownResult()
        active_players = [p for p in players if p.is_active]

        for pot in pots:
            if not pot.eligible_players:
                continue

            eligible = [p for p in players
                        if p.player_id in pot.eligible_players and p.is_active]

            if len(eligible) == 1:
                # Single winner
                winner = eligible[0]
                winner.win_chips(pot.amount)
                result.record_win(winner.player_id, pot.amount)
                continue

            # Multiple winners - find best hand(s)
            best_score = None
            winners = []

            for p in eligible:
                if p.player_id not in scores:
                    continue

                score = scores[p.player_id]
                # Debug: print score comparison
                # print(f"  DEBUG: {p.player_id} score={score}, best_score={best_score}")
                if best_score is None or score > best_score:
                    best_score = score
                    winners = [p]
                elif score == best_score:
                    winners.append(p)
            
            # Debug: print winners
            # print(f"  DEBUG: pot={pot.amount}, winners={[w.player_id for w in winners]}, best_score={best_score}")

            # Split pot among winners
            split_amount = pot.amount // len(winners)
            remainder = pot.amount - split_amount * len(winners)

            for w in winners:
                w.win_chips(split_amount)
                result.record_win(w.player_id, split_amount)

            # Award remainder to first winner (closest to dealer)
            if remainder > 0 and winners:
                first_winner = min(
                    winners,
                    key=lambda p: (players.index(p) - dealer_idx - 1) % num_players
                )
                first_winner.win_chips(remainder)
                result.record_win(first_winner.player_id, remainder)

        return result
