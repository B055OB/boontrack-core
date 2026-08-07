from typing import List, Dict, Any
from app.core.ranking_config import RANKING_CONFIG

class RankingService:
    @staticmethod
    def calculate_score(
        matched_weight: float,
        quality_score: float,
        popularity_score: float,
        asset_lang: str,
        user_lang: str = "id",
        asset_country: str = "ID",
        user_country: str = "ID"
    ) -> Dict[str, Any]:
        # CTO Decision #040 & #044: Explainable Score Breakdown & Configurable Weights
        cfg = RANKING_CONFIG
        
        kw_score = matched_weight * cfg["keyword_weight"]
        qual_score = (quality_score or 5.0) * (cfg["quality_weight"] / 10.0)
        pop_score = min((popularity_score or 0.0) * 2.0, cfg["popularity_weight"])
        lang_score = cfg["language_bonus"] if asset_lang == user_lang else 0.0
        ctry_score = cfg["country_bonus"] if asset_country == user_country else 0.0
        
        final_score = round(kw_score + qual_score + pop_score + lang_score + ctry_score, 2)
        
        return {
            "final_score": final_score,
            "breakdown": {
                "keyword": round(kw_score, 2),
                "quality": round(qual_score, 2),
                "popularity": round(pop_score, 2),
                "language": round(lang_score, 2),
                "country": round(ctry_score, 2)
            }
        }

    def rank_candidates(self, candidates: List[Dict[str, Any]], user_lang: str = "id", user_country: str = "ID") -> List[Dict[str, Any]]:
        ranked_list = []
        for cand in candidates:
            score_data = self.calculate_score(
                matched_weight=cand["matched_weight"],
                quality_score=cand["asset"].quality_score,
                popularity_score=cand["asset"].popularity_score,
                asset_lang=cand["asset"].language,
                user_lang=user_lang,
                asset_country=cand["asset"].country,
                user_country=user_country
            )
            ranked_list.append({
                "asset": cand["asset"],
                "deliveries": cand["deliveries"],
                "matched_keyword": cand["matched_keyword"],
                "score": score_data["final_score"],
                "score_breakdown": score_data["breakdown"]
            })
        
        ranked_list.sort(key=lambda x: x["score"], reverse=True)
        return ranked_list
