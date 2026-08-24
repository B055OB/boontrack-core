import re
import difflib
from typing import List, Dict, Any, Tuple, Optional
from app.core.ai.fallback.confidence import evaluate_confidence, MatchConfidence

class LocalKnowledgeMatcher:
    def __init__(self, rules: List[Dict[str, Any]]):
        self.rules = rules

    def _normalize(self, text: str) -> str:
        return re.sub(r"[^\w\s]", "", (text or "").lower()).strip()

    def _tokenize(self, text: str) -> set:
        return {w for w in self._normalize(text).split() if len(w) > 2}

    def find_match(self, query: str) -> Tuple[MatchConfidence, float, Optional[str], Optional[str]]:
        raw_query = self._normalize(query)
        query_tokens = self._tokenize(query)

        if not raw_query:
            return MatchConfidence.LOW, 0.0, None, None

        best_score = 0.0
        best_rule = None

        for rule in self.rules:
            keywords = rule.get("keywords", [])
            exact_phrases = rule.get("exact_phrases", [])
            boost_words = rule.get("confidence_boost", [])

            # 1. Exact Match (Score = 1.0)
            for phrase in exact_phrases:
                if self._normalize(phrase) == raw_query:
                    return MatchConfidence.HIGH, 1.0, rule.get("answer"), rule.get("intent")

            # 2. Substring & Token Overlap
            rule_tokens = set()
            exact_substr_count = 0
            for kw in keywords:
                norm_kw = self._normalize(kw)
                if norm_kw in raw_query:
                    exact_substr_count += 1
                rule_tokens.update(self._tokenize(kw))

            if not rule_tokens:
                continue

            common_tokens = query_tokens.intersection(rule_tokens)
            token_ratio = len(common_tokens) / len(rule_tokens)
            
            # 3. Fuzzy Match
            fuzzy_ratio = max([difflib.SequenceMatcher(None, kw, raw_query).ratio() for kw in keywords] or [0.0])
            score = (token_ratio * 0.4) + (fuzzy_ratio * 0.3) + min(0.3, exact_substr_count * 0.15)

            # 4. Boost
            boost_hits = sum(1 for b in boost_words if self._normalize(b) in raw_query)
            if boost_hits > 0:
                score += min(0.15, boost_hits * 0.08)

            final_score = min(1.0, score)
            if final_score > best_score:
                best_score = final_score
                best_rule = rule

        conf_level, is_allowed = evaluate_confidence(best_score)
        if is_allowed and best_rule:
            return conf_level, best_score, best_rule.get("answer"), best_rule.get("intent")

        return MatchConfidence.LOW, best_score, None, None