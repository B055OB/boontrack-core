# app/core/ranking_config.py
# CTO Decision #044: Configurable Ranking Weights

RANKING_CONFIG = {
    "keyword_weight": 40.0,      # Poin maks dari match weight (0-40)
    "quality_weight": 20.0,      # Poin maks dari quality score (0-20)
    "popularity_weight": 20.0,   # Poin maks dari popularity (0-20)
    "language_bonus": 10.0,      # Bonus jika bahasa cocok (10)
    "country_bonus": 10.0        # Bonus jika negara cocok (10)
}
