#!/usr/bin/env python3
"""inputThinker: directs how layerAssigner weights input tokens.

layerAssigner calls :func:`weight` once per token (words, punctuation, and the
media/timestamp tokens too). The default policy gives every node a weight of 1.
Replace the body of :func:`weight` to make some tokens heavier than others.
"""

DEFAULT_WEIGHT = 1


def weight(token, index, context=None):
    """Return the initial weight for ``token`` at position ``index``.

    ``context`` is reserved for future use (e.g. the full token list, the channel,
    or the login state) so the policy can consider surroundings.
    """
    # TODO: real weighting policy. For now every node defaults to 1.
    return DEFAULT_WEIGHT
