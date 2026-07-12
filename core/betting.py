from typing import Dict, List, Set

class Pot:
    def __init__(self):
        self.amount = 0
        self.eligible_players = set()

    def __repr__(self):
        return f"Pot({self.amount}, eligible={len(self.eligible_players)})"

class PotManager:
    def __init__(self):
        # player_id -> total chips contributed in the current hand
        self.contributions: Dict[str, int] = {}
        self.pots: List[Pot] = []

    def add_contribution(self, player_id: str, amount: int):
        if player_id not in self.contributions:
            self.contributions[player_id] = 0
        self.contributions[player_id] += amount

    def calculate_pots(self, active_player_ids: List[str], all_in_player_ids: List[str] = None):
        """
        Builds the main pot and side pots based on player contributions.
        Should be called at the end of the hand (showdown) or when dealing with all-ins.

        Side pot boundaries are set only by all-in caps. A player who folded
        for less than others just leaves their chips in whichever pot(s) they
        reached - it doesn't split off a pot of its own.

        Args:
            active_player_ids: List of player IDs who haven't folded (eligible to win pots)
            all_in_player_ids: List of player IDs who are all-in (capped, can't contribute more)
        """
        self.pots = []
        contribs = {pid: amt for pid, amt in self.contributions.items() if amt > 0}
        if not contribs:
            return

        all_in_player_ids = set(all_in_player_ids or [])
        active_set = set(active_player_ids)
        caps = sorted({amt for pid, amt in contribs.items() if pid in all_in_player_ids})

        prev_level = 0
        for cap in caps + [max(contribs.values())]:
            level_amount = cap - prev_level
            if level_amount <= 0:
                prev_level = cap
                continue

            pot = Pot()
            contributors_at_level = []
            for pid, total in contribs.items():
                take = min(level_amount, total - prev_level)
                if take <= 0:
                    continue
                pot.amount += take
                contributors_at_level.append(pid)

            # All players who contributed at this level are eligible for this pot.
            # Folded players forfeit their share to remaining eligible players.
            active_at_level = [pid for pid in contributors_at_level if pid in active_set]

            # If all players at this level folded (shouldn't happen normally),
            # give to remaining active players
            pot.eligible_players = set(active_at_level) if active_at_level else active_set

            if pot.amount > 0:
                self.pots.append(pot)
            prev_level = cap

    def total_pot(self) -> int:
        return sum(amt for amt in self.contributions.values())

class BetManager:
    def __init__(self, big_blind: int):
        self.big_blind = big_blind
        self.reset_round()
        
    def reset_round(self):
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.player_bets_this_round: Dict[str, int] = {}
        self.last_raiser: str = None
        
    def process_bet(self, player_id: str, amount: int, is_raise: bool = False):
        if player_id not in self.player_bets_this_round:
            self.player_bets_this_round[player_id] = 0
            
        previous_bet = self.player_bets_this_round[player_id]
        new_total = previous_bet + amount
        self.player_bets_this_round[player_id] = new_total
        
        if new_total > self.current_bet:
            raise_amount = new_total - self.current_bet
            if raise_amount >= self.min_raise:
                self.min_raise = raise_amount
            self.current_bet = new_total
            self.last_raiser = player_id

    def get_amount_to_call(self, player_id: str) -> int:
        current_player_bet = self.player_bets_this_round.get(player_id, 0)
        return self.current_bet - current_player_bet
