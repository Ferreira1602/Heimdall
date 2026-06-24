"""
app/services/estimator.py — estimativas de consumo futuro.

Combina dois sinais a partir do histórico mensal:
  1) Média móvel ponderada (mês recente pesa mais)
  2) Tendência linear (regressão simples) para capturar crescimento/queda

A estimativa final é a média dos dois, com piso em zero.
"""


def _weighted_avg(values: list[float]) -> float:
    if not values:
        return 0.0
    weights = list(range(1, len(values) + 1))  # mais peso ao mais recente
    s = sum(v * w for v, w in zip(values, weights))
    return s / sum(weights)


def _linear_next(values: list[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    if n == 1:
        return values[0]
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, values)) / den
    intercept = my - slope * mx
    return slope * n + intercept


def estimate_next(values: list[float]) -> float:
    """values em ordem cronológica (mais antigo -> mais recente)."""
    if not values:
        return 0.0
    est = (_weighted_avg(values) + _linear_next(values)) / 2
    return max(0.0, round(est, 4))


def trend_pct(values: list[float]) -> float:
    """Variação % do último mês vs penúltimo."""
    if len(values) < 2 or values[-2] == 0:
        return 0.0
    return round((values[-1] - values[-2]) / values[-2] * 100, 1)
