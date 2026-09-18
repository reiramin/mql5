"""mql5bot.factory.providers — community/research provider interfaces
(mission §12/§65/§66).

A provider returns NORMALIZED RESEARCH MATERIAL — never trusted
executable code.  The default installation is paste-first: network
fetching is opt-in per provider and disabled in this delivery
(unavailable ⇒ explicit `Unavailable` result, never fabrication).

Every provider result carries provenance and is treated as
UNTRUSTED DATA downstream (see strategy_security policy): source text
can never instruct the system.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchMaterial:
    """Normalized, provenance-stamped source material."""

    source_type: str                 # HUMAN/COMMUNITY/TRADINGVIEW/...
    title: str
    text: str                        # the user-provided/fetched content
    url: str | None = None
    author: str | None = None
    platform: str | None = None
    retrieved_at: str | None = None
    license_note: str | None = None
    warnings: tuple = ()

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps({"title": self.title, "text": self.text,
                        "url": self.url},
                       sort_keys=True, ensure_ascii=False)
            .encode("utf-8")).hexdigest()

    def provenance(self) -> dict:
        return {"type": self.source_type, "url": self.url,
                "author": self.author, "platform": self.platform,
                "retrieved_at": self.retrieved_at,
                "license_note": self.license_note}


@dataclass(frozen=True)
class ProviderResult:
    material: ResearchMaterial | None = None
    status: str = "UNAVAILABLE"      # OK | UNAVAILABLE | REFUSED
    why: str = ""


class ICommunityStrategyProvider:
    """Provider contract (mission §65).  Subclasses implement fetch;
    the base refuses by default (network OFF is the safe default)."""

    name = "base"

    def fetch(self, reference: str) -> ProviderResult:
        return ProviderResult(
            status="REFUSED",
            why=f"provider {self.name!r} has no network access in "
                "this installation; paste the source text instead "
                "(paste-first policy, SPEC §10.1/HANDOFF §2)")


class UserSubmissionProvider(ICommunityStrategyProvider):
    """The ALWAYS-available path: the user provides the text."""

    name = "user_submission"

    def fetch(self, reference: str) -> ProviderResult:
        text = (reference or "").strip()
        if not text:
            return ProviderResult(status="REFUSED",
                                  why="empty submission")
        if len(text) > 100_000:
            return ProviderResult(
                status="REFUSED",
                why="submission exceeds 100k chars (resource limit)")
        return ProviderResult(
            status="OK",
            material=ResearchMaterial(
                source_type="USER_TEXT", title=text.splitlines()[0][:80],
                text=text,
                retrieved_at="", warnings=(
                    "user-provided text is untrusted data; claims are "
                    "AUTHOR_CLAIM, never evidence")))


class TradingViewProvider(ICommunityStrategyProvider):
    """URL-based TradingView import: NOT enabled by default (ToS +
    robots + legal review required — mission §66).  It records the
    user-provided URL as provenance and returns the PASTE path."""

    name = "tradingview"

    def fetch(self, reference: str) -> ProviderResult:
        return ProviderResult(
            status="UNAVAILABLE",
            why="TradingView auto-fetch is disabled (ToS/robots review "
                "pending); paste the strategy description and the URL "
                "is kept as provenance")


class ArticleProvider(ICommunityStrategyProvider):
    name = "article"

    def fetch(self, reference: str) -> ProviderResult:
        return ProviderResult(
            status="UNAVAILABLE",
            why="article auto-fetch is disabled; paste the article text")


class ResearchPaperProvider(ICommunityStrategyProvider):
    name = "research_paper"

    def fetch(self, reference: str) -> ProviderResult:
        return ProviderResult(
            status="UNAVAILABLE",
            why="paper auto-fetch is disabled; paste the relevant "
                "strategy section")


PROVIDERS: dict[str, type[ICommunityStrategyProvider]] = {
    "user_submission": UserSubmissionProvider,
    "tradingview": TradingViewProvider,
    "article": ArticleProvider,
    "research_paper": ResearchPaperProvider,
}


def get_provider(name: str) -> ICommunityStrategyProvider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise KeyError(f"unknown provider {name!r}; known: "
                       f"{sorted(PROVIDERS)}") from None
