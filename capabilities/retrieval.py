from __future__ import annotations

import re
from dataclasses import dataclass

from mcp_client.models import MCPServerSummary

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class ServerRetrievalScore:
    server: MCPServerSummary
    score: float
    reasons: tuple[str, ...]


class LexicalServerSignal:
    def score(self, query: str, servers: list[MCPServerSummary]) -> list[ServerRetrievalScore]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        results: list[ServerRetrievalScore] = []
        for server in servers:
            weighted_terms = _weighted_terms(server)
            score = 0.0
            reasons: list[str] = []
            for term, weight in weighted_terms:
                normalized = term.lower()
                term_tokens = _tokens(term)
                if normalized and normalized in query.lower():
                    score += weight
                    reasons.append(f"matched term: {term}")
                    continue
                overlap = query_tokens.intersection(term_tokens)
                if overlap:
                    score += weight * min(1.0, len(overlap) / max(len(term_tokens), 1))
                    reasons.append(f"matched tokens: {', '.join(sorted(overlap))}")
            if score > 0:
                results.append(ServerRetrievalScore(server=server, score=score, reasons=tuple(reasons[:3])))
        results.sort(key=lambda item: (-item.score, item.server.name))
        return results


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in TOKEN_RE.findall(text or "")}


def _weighted_terms(server: MCPServerSummary) -> list[tuple[str, float]]:
    terms: list[tuple[str, float]] = [
        (server.name, 3.0),
        (server.description, 1.0),
    ]
    terms.extend((item, 2.5) for item in server.aliases)
    terms.extend((item, 2.5) for item in server.abbreviations)
    terms.extend((item, 2.0) for item in server.keywords)
    terms.extend((item, 1.5) for item in server.synonyms)
    terms.extend((item, 1.2) for item in server.tags)
    return [(term, weight) for term, weight in terms if term]
