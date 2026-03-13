from evaluator import HandEvaluator, HandRank
from card import Card, Suit

def test():
    c1 = Card(14, Suit.SPADES)
    c2 = Card(13, Suit.SPADES)
    c3 = Card(12, Suit.SPADES)
    c4 = Card(11, Suit.SPADES)
    c5 = Card(10, Suit.SPADES)
    c6 = Card(2, Suit.HEARTS)
    c7 = Card(3, Suit.CLUBS)
    
    score, best_hand = HandEvaluator.evaluate([c1, c2], [c3, c4, c5, c6, c7])
    print(f"Score: {score[0]} ({HandRank.to_string(score[0])}), tiebreak: {score[1:]}")
    print(f"Hand: {best_hand}")

test()
