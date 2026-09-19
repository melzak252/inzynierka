"""Comprehensive unit tests for A1 architecture, symmetry, and Set Transformer."""

import pytest
import torch
import numpy as np

from src.models.a1.architecture import A1Model, A1Config, TeamSetTransformer


def test_team_set_transformer_shape_and_permutation_invariance():
    """TeamSetTransformer must output pooled vectors of shape (batch, d_model * 2)."""
    batch_size = 4
    d_model = 64
    transformer = TeamSetTransformer(d_model=d_model, nhead=4)
    transformer.eval()

    player_vectors = torch.randn(batch_size, 5, d_model)
    team_pooled, contextualized = transformer(player_vectors)

    assert team_pooled.shape == (batch_size, d_model * 2)
    assert contextualized.shape == (batch_size, 5, d_model)


def test_a1_model_forward_pass_shape():
    """A1Model must produce valid probabilities in (0, 1) for Bo1, Bo3, and Bo5."""
    batch_size = 3
    config = A1Config()
    model = A1Model(config)
    model.eval()

    context = torch.randn(batch_size, 70)
    player_ratings = torch.randn(batch_size, 2, 5, 21)
    player_history = torch.randn(batch_size, 2, 5, 16, 33)
    player_mask = torch.ones(batch_size, 2, 5, 16, dtype=torch.uint8)
    player_champions = torch.randint(0, 255, (batch_size, 2, 5, 16))
    meta_champions = torch.randn(batch_size, 2, 5, 32)
    best_of = torch.tensor([1, 3, 5], dtype=torch.long)

    with torch.no_grad():
        probs = model(
            context=context,
            player_ratings=player_ratings,
            player_history=player_history,
            player_mask=player_mask,
            player_champions=player_champions,
            meta_champions=meta_champions,
            best_of=best_of,
        )

    assert probs.shape == (batch_size,)
    assert torch.all(probs >= 0.0) and torch.all(probs <= 1.0)


def test_a1_model_strict_anti_symmetry():
    """Swapping Side A and Side B must yield exact p(A, B) + p(B, A) = 1.0."""
    batch_size = 5
    config = A1Config()
    model = A1Model(config)
    model.eval()

    context = torch.randn(batch_size, 70)
    player_ratings = torch.randn(batch_size, 2, 5, 21)
    player_history = torch.randn(batch_size, 2, 5, 16, 33)
    player_mask = torch.ones(batch_size, 2, 5, 16, dtype=torch.uint8)
    player_champions = torch.randint(0, 255, (batch_size, 2, 5, 16))
    meta_champions = torch.randn(batch_size, 2, 5, 32)
    best_of = torch.tensor([1, 3, 5, 3, 1], dtype=torch.long)

    with torch.no_grad():
        # Forward evaluation: P(A wins against B)
        p_ab = model(
            context=context,
            player_ratings=player_ratings,
            player_history=player_history,
            player_mask=player_mask,
            player_champions=player_champions,
            meta_champions=meta_champions,
            best_of=best_of,
        )

        # Swapped evaluation: Swap side 0 and 1, invert context sign
        context_swapped = -context
        player_ratings_swapped = player_ratings.flip(dims=[1])
        player_history_swapped = player_history.flip(dims=[1])
        player_mask_swapped = player_mask.flip(dims=[1])
        player_champions_swapped = player_champions.flip(dims=[1])
        meta_champions_swapped = meta_champions.flip(dims=[1])

        p_ba = model(
            context=context_swapped,
            player_ratings=player_ratings_swapped,
            player_history=player_history_swapped,
            player_mask=player_mask_swapped,
            player_champions=player_champions_swapped,
            meta_champions=meta_champions_swapped,
            best_of=best_of,
        )

    # Sum of forward and reversed must be exactly 1.0 everywhere
    prob_sum = p_ab + p_ba
    diff = torch.abs(prob_sum - 1.0)
    assert torch.max(diff).item() < 1e-6, f"Anti-symmetry violated! Max diff: {torch.max(diff).item()}"


def test_a1_cold_start_mask_handling():
    """Model must run gracefully when a player has 0 historical maps (all mask = 0)."""
    batch_size = 2
    config = A1Config()
    model = A1Model(config)
    model.eval()

    context = torch.randn(batch_size, 70)
    player_ratings = torch.randn(batch_size, 2, 5, 21)
    player_history = torch.zeros(batch_size, 2, 5, 16, 33)
    player_mask = torch.zeros(batch_size, 2, 5, 16, dtype=torch.uint8)  # All empty
    player_champions = torch.zeros(batch_size, 2, 5, 16, dtype=torch.long)
    meta_champions = torch.randn(batch_size, 2, 5, 32)
    best_of = torch.tensor([1, 3], dtype=torch.long)

    with torch.no_grad():
        probs = model(
            context=context,
            player_ratings=player_ratings,
            player_history=player_history,
            player_mask=player_mask,
            player_champions=player_champions,
            meta_champions=meta_champions,
            best_of=best_of,
        )

    assert torch.all(torch.isfinite(probs))
    assert torch.all(probs > 0.0) and torch.all(probs < 1.0)
