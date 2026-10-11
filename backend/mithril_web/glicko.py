"""Glicko-2 for one game at a time (Glickman, "Example of the Glicko-2 system", 2013)."""

import math
from dataclasses import dataclass

SCALE = 173.7178
START = 1500.0
START_RD = 350.0
START_VOLATILITY = 0.06
TAU = 0.5
EPSILON = 0.000001


@dataclass(frozen=True)
class Strength:
    rating: float = START
    rd: float = START_RD
    volatility: float = START_VOLATILITY


def idle(player: Strength, periods: float) -> Strength:
    """Uncertainty grows while a player doesn't play; the rating itself never moves."""
    if periods <= 0:
        return player
    phi = math.sqrt((player.rd / SCALE) ** 2 + periods * player.volatility**2)
    return Strength(player.rating, min(START_RD, phi * SCALE), player.volatility)


def _g(phi):
    return 1 / math.sqrt(1 + 3 * phi**2 / math.pi**2)


def _volatility(sigma, phi, v, delta):
    a = math.log(sigma**2)

    def f(x):
        ex = math.exp(x)
        return ex * (delta**2 - phi**2 - v - ex) / (2 * (phi**2 + v + ex) ** 2) - (x - a) / TAU**2

    low = a
    if delta**2 > phi**2 + v:
        high = math.log(delta**2 - phi**2 - v)
    else:
        k = 1
        while f(a - k * TAU) < 0:
            k += 1
        high = a - k * TAU
    f_low, f_high = f(low), f(high)
    while abs(high - low) > EPSILON:
        middle = low + (low - high) * f_low / (f_high - f_low)
        f_middle = f(middle)
        if f_middle * f_high <= 0:
            low, f_low = high, f_high
        else:
            f_low /= 2
        high, f_high = middle, f_middle
    return math.exp(low / 2)


def update(player: Strength, games) -> Strength:
    """The player's rating after a period's games: (opponent, score) pairs, where the score
    is 1 for a win, 0.5 for a draw and 0 for a loss."""
    mu, phi = (player.rating - START) / SCALE, player.rd / SCALE
    information = improvement = 0.0
    for opponent, score in games:
        mu_j, phi_j = (opponent.rating - START) / SCALE, opponent.rd / SCALE
        g = _g(phi_j)
        expected = 1 / (1 + math.exp(-g * (mu - mu_j)))
        information += g**2 * expected * (1 - expected)
        improvement += g * (score - expected)
    v = 1 / information
    sigma = _volatility(player.volatility, phi, v, v * improvement)
    phi_star = math.sqrt(phi**2 + sigma**2)
    phi_new = 1 / math.sqrt(1 / phi_star**2 + 1 / v)
    return Strength((mu + phi_new**2 * improvement) * SCALE + START, phi_new * SCALE, sigma)


def soften(player: Strength) -> Strength:
    """The monthly soft reset: a quarter of the way back to 1500, and 100 less certain."""
    return Strength(
        player.rating + (START - player.rating) / 4,
        min(START_RD, player.rd + 100),
        player.volatility,
    )
