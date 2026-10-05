import logging

from aivi.domain.enums import Actor

log = logging.getLogger(__name__)


class WriteDenied(PermissionError):
    pass


class NotFound(LookupError):
    pass


def require(actor: Actor, allowed: set[Actor], action: str) -> None:
    if actor not in allowed:
        log.warning("write denied actor=%s action=%s", actor.value, action)
        raise WriteDenied(f"{actor.value} cannot {action}")


def require_documents(actor: Actor) -> None:
    require(actor, {Actor.PIPELINE, Actor.OWNER}, "write documents")


def require_metrics(actor: Actor) -> None:
    require(actor, {Actor.PIPELINE, Actor.OWNER}, "write metric observations")


def require_active_knowledge(actor: Actor) -> None:
    require(actor, {Actor.OWNER}, "write active knowledge")


def require_thesis(actor: Actor) -> None:
    require(actor, {Actor.OWNER}, "write investment thesis")


def require_proposal(actor: Actor) -> None:
    require(actor, {Actor.PIPELINE, Actor.RESEARCH_AGENT, Actor.OWNER}, "create proposal")


def require_approve(actor: Actor) -> None:
    require(actor, {Actor.OWNER}, "approve proposal")


def require_memory(actor: Actor) -> None:
    require(actor, {Actor.RESEARCH_AGENT, Actor.OWNER}, "write memory")


def require_conversation(actor: Actor) -> None:
    require(actor, {Actor.RESEARCH_AGENT, Actor.OWNER}, "write conversation")


def require_watchlist(actor: Actor) -> None:
    require(actor, {Actor.OWNER}, "write watchlist")
