"""Reviewed behavior contracts for standalone practice tasks."""

from __future__ import annotations

import math
import re

from pydantic import JsonValue

from ..core.models import CardGenerationContext, PythonBehaviorCase, PythonBehaviorContract

PPO_CLIPPED_LOSS_REFERENCE = "trainer/ppo-clipped-loss/v1"
PPO_CLIPPED_LOSS_FUNCTION = "ppo_clip_loss"
_PPO = re.compile(r"\bppo\b|近端策略优化", re.IGNORECASE)
_PPO_LOSS = re.compile(r"\bclip\w*|裁剪|截断", re.IGNORECASE)


def use_ppo_loss_reference(context: CardGenerationContext, source: str, card_type: str) -> bool:
    # An IDE file, resource or plan can define a different task signature.
    if (
        card_type != "practice" or source != "conversation_gap" or context.resource_id
        or context.current_file_path or context.plan_binding or context.plan_stage_id
    ):
        return False
    topic = f"{context.focus_area} {context.target_skill}"
    request = f"{context.target_skill} {context.context_hint}".lower()
    return bool(
        _PPO.search(topic) and _PPO_LOSS.search(topic)
        and any(word in request for word in ("loss", "损失"))
        and any(word in request for word in ("python", "标准库"))
        and any(word in request for word in ("list", "列表"))
        and any(word in request for word in ("log prob", "log_prob", "对数概率"))
    )


def ppo_clipped_loss_contract() -> PythonBehaviorContract:
    """Freeze outputs against the negative batch mean of PPO Eq. (7).

    Schulman et al., Proximal Policy Optimization Algorithms, §3
    https://arxiv.org/abs/1707.06347
    """
    log_two = math.log(2.0)
    inputs = [
        ([0.0], [0.0], [0.0], 0.25),
        ([log_two], [0.0], [2.0], 0.25),
        ([-log_two], [0.0], [-2.0], 0.25),
        ([log_two, -log_two], [0.0, 0.0], [-1.0, 2.0], 0.25),
        ([0.0, log_two], [log_two, log_two], [1.0, -1.0], 0.2),
    ]
    cases = []
    for new_log_probs, old_log_probs, advantages, epsilon in inputs:
        terms = []
        for new, old, advantage in zip(new_log_probs, old_log_probs, advantages, strict=True):
            ratio = math.exp(new - old)
            clipped = min(1.0 + epsilon, max(1.0 - epsilon, ratio))
            terms.append(min(ratio * advantage, clipped * advantage))
        cases.append(PythonBehaviorCase(
            args=[
                list[JsonValue](new_log_probs), list[JsonValue](old_log_probs),
                list[JsonValue](advantages), epsilon,
            ],
            expected=-math.fsum(terms) / len(terms),
        ))
    return PythonBehaviorContract(
        function=PPO_CLIPPED_LOSS_FUNCTION, cases=cases, reference_id=PPO_CLIPPED_LOSS_REFERENCE,
    )
