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

    def calculate_pots(self, active_player_ids: List[str]):
        """
        Builds the main pot and side pots based on player contributions.
        Should be called at the end of the hand (showdown) or when dealing with all-ins.
        
        Args:
            active_player_ids: List of player IDs who haven't folded (eligible to win pots)
        """
        self.pots = []
        contribs = {pid: amt for pid, amt in self.contributions.items() if amt > 0}

        while contribs:
            # Find the smallest contribution level
            min_contrib = min(contribs.values())

            pot = Pot()
            pot.amount = 0
            players_at_this_level = []

            # Collect contributions at this level
            for pid in list(contribs.keys()):
                contribs[pid] -= min_contrib
                pot.amount += min_contrib
                players_at_this_level.append(pid)

                if contribs[pid] == 0:
                    del contribs[pid]

            # All players who contributed at this level are eligible for this pot
            # Folded players forfeit their share to remaining eligible players
            active_at_level = [pid for pid in players_at_this_level if pid in active_player_ids]
            
            # If all players at this level folded (shouldn't happen normally), 
            # give to remaining active players
            if not active_at_level:
                pot.eligible_players = set(active_player_ids)
            else:
                pot.eligible_players = set(active_at_level)

            if pot.amount > 0:
                self.pots.append(pot)

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
