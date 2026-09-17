"""The six countries shared by the history generator and the live traffic (docs/build-spec.md §5.2, §9)."""

# Country mix: name and Eurostat population on 1 January 2026 (tps00001, updated
# 2026-07-21; build-spec §5.2, §9.3)
COUNTRIES = {
    "FR": ("France", 69112309),
    "DE": ("Germany", 83467117),
    "IT": ("Italy", 58942828),
    "ES": ("Spain", 49590099),
    "NL": ("Netherlands", 18130208),
    "BE": ("Belgium", 11955308),
}

# Mobile numbers in national format, digits only, from simplified mobile
# prefixes: (prefix, total digits) (§5.2, §9.7, §9.10)
MOBILE_NUMBERS = {
    "FR": [("06", 10), ("07", 10)],
    "DE": [("015", 12), ("016", 11), ("016", 12), ("017", 11), ("017", 12)],
    "IT": [("3", 10)],
    "ES": [("6", 9), ("7", 9)],
    "NL": [("06", 10)],
    "BE": [("04", 10)],
}
