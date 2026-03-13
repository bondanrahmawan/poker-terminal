# Poker Terminal Game

A terminal-based Texas Hold'em Poker Game written in Python. This implementation supports local play against configurable AI bots.

## Prerequisites

- Python 3.14.3 or higher

## How to Run

1. Open your terminal.
2. Navigate to the project directory:
   ```bash
   cd /Users/bondan/Desktop/random/poker
   ```
3. Run the main script:
   ```bash
   python3 main.py
   ```
4. Follow the on-screen prompts to set your player name, the number of bots you want to play against, your starting chips, and the big blind amount.

## How to Play

During your turn, the terminal will display your hole cards, any community cards, the current pot size, and the amount needed to call. You can perform the following actions by typing the corresponding letter or word:

- **Check/Call (`c` or `check` or `call`)**: Match the current highest bet. If there is no bet to match, this action "checks", passing the turn to the next player without betting.
- **Bet/Raise (`b` or `r` or `bet` or `raise`)**: Increase the current bet. You will be prompted to enter a specific total amount you want to raise to.
- **Fold (`f` or `fold`)**: Discard your hand and forfeit your interest in the current pot.
- **All-in (`a` or `all-in`)**: Bet all of your remaining chips.
- **Status (`s` or `status`)**: Display the current chip counts and active state of all players at the table.

## Texas Hold'em Rules

1. **The Deal**: Each player is dealt two private cards ("hole cards").
2. **Pre-Flop**: The first betting round occurs. The player to the left of the dealer posts the "Small Blind", and the next player posts the "Big Blind".
3. **The Flop**: Three community cards are dealt face up on the board. The second betting round occurs.
4. **The Turn**: A fourth community card is dealt face up. The third betting round occurs.
5. **The River**: A fifth and final community card is dealt face up. The final betting round occurs.
6. **The Showdown**: Remaining players reveal their hole cards. The player with the best 5-card hand (combining their 2 hole cards and the 5 community cards) wins the pot.

### Hand Rankings (Highest to Lowest)

1. **Straight Flush**: Five consecutive cards of the same suit.
2. **Four of a Kind**: Four cards of the same rank.
3. **Full House**: Three of a kind combined with a pair.
4. **Flush**: Any five cards of the same suit.
5. **Straight**: Five consecutive cards of mixed suits.
6. **Three of a Kind**: Three cards of the same rank.
7. **Two Pair**: Two different pairs.
8. **One Pair**: Two cards of the same rank.
9. **High Card**: When no other hand is made, the highest single card.
