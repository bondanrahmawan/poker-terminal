"""Engine exceptions."""


class IllegalActionError(Exception):
    """Raised by Game.submit_action for out-of-turn or invalid actions."""
