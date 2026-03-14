from typing import Tuple
from player import Player, PlayerAction

class TerminalPlayer(Player):
    def get_action(self, game_state: dict) -> Tuple[str, int]:
        min_call = game_state.get('min_call', 0)
        min_raise = game_state.get('min_raise', 0)
        pot_size = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])
        
        print("\n" + "="*40)
        print(f"Player: {self.name} | Chips: {self.chips}")
        print(f"Hole Cards: {self.hole_cards}")
        if community_cards:
            print(f"Community:  {community_cards}")
        print(f"Pot Size:   {pot_size}")
        print(f"To Call:    {min_call}")
        print("="*40)
        
        while True:
            if min_call == 0:
                print("Options: (c)heck, (b)et, (f)old, (a)ll-in, (s)tatus")
            else:
                print(f"Options: (c)all {min_call}, (r)aise, (f)old, (a)ll-in, (s)tatus")
                
            choice = input(f"{self.name}, your action: ").strip().lower()
            
            if choice in ['s', 'status']:
                print("\n--- Player Status ---")
                players_info = game_state.get('players_info', [])
                # Sort by chip count (descending)
                sorted_players = sorted(players_info, key=lambda p: p[1], reverse=True)
                for p_name, p_chips, p_active in sorted_players:
                    status_str = "Active" if p_active else "Folded/Out"
                    print(f"{p_name:<15} | Chips: {p_chips:<6} | Status: {status_str}")
                print("---------------------\n")
                continue

            if choice in ['f', 'fold']:
                return PlayerAction.FOLD, 0
            
            elif choice in ['c', 'check', 'call']:
                if min_call == 0:
                    return PlayerAction.CHECK, 0
                else:
                    call_amt = min(self.chips, min_call)
                    if call_amt == self.chips:
                        return PlayerAction.ALL_IN, call_amt
                    return PlayerAction.CALL, call_amt
                    
            elif choice in ['b', 'r', 'bet', 'raise']:
                while True:
                    amt_str = input(f"Enter total raise amount (min {min_raise + min_call}): ")
                    if amt_str.isdigit():
                        amt = int(amt_str)
                        if amt >= min_raise + min_call and amt <= self.chips:
                            if amt == self.chips:
                                return PlayerAction.ALL_IN, amt
                            return PlayerAction.RAISE, amt
                        else:
                            print(f"Invalid amount. Must be between {min_raise + min_call} and {self.chips}.")
                    else:
                        print("Please enter a valid number.")
                        
            elif choice in ['a', 'all-in', 'allin']:
                return PlayerAction.ALL_IN, self.chips
                
            else:
                print("Invalid choice. Try again.")

