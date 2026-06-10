from dataclasses import dataclass


@dataclass(frozen=True)
class VCFirm:
    name: str
    portfolio_url: str
    locations: tuple[str, ...]
    source: str = "scrape"  # scrape | yc_api


NYC_KEYWORDS = frozenset(
    {"new york", "nyc", "manhattan", "brooklyn", "new york city", "ny"}
)

# Curated NYC / Manhattan-focused VC firms (expandable).
VC_REGISTRY: list[VCFirm] = [
    VCFirm("Primary Venture Partners", "https://www.primary.vc/portfolio", ("new york", "nyc", "manhattan")),
    VCFirm("BoxGroup", "https://www.boxgroup.com/portfolio", ("new york", "nyc", "manhattan")),
    VCFirm("Union Square Ventures", "https://www.usv.com/companies/", ("new york", "nyc", "manhattan")),
    VCFirm("Lerer Hippeau", "https://www.lererhippeau.com/portfolio", ("new york", "nyc", "manhattan")),
    VCFirm("FirstMark", "https://firstmark.com/portfolio/", ("new york", "nyc", "manhattan")),
    VCFirm("Thrive Capital", "https://thrivecap.com/", ("new york", "nyc", "manhattan")),
    VCFirm("Inspired Capital", "https://www.inspiredcapital.com/companies", ("new york", "nyc", "manhattan")),
    VCFirm("Greycroft", "https://www.greycroft.com/portfolio/", ("new york", "nyc", "manhattan")),
    VCFirm("Two Sigma Ventures", "https://twosigmaventures.com/portfolio/", ("new york", "nyc", "manhattan")),
    VCFirm("Bedrock", "https://bedrockcap.com/companies", ("new york", "nyc", "manhattan")),
    VCFirm("Felicis", "https://www.felicis.com/portfolio", ("new york", "nyc", "manhattan", "san francisco")),
    VCFirm("Bessemer Venture Partners", "https://www.bvp.com/companies", ("new york", "nyc", "manhattan")),
    VCFirm("Lux Capital", "https://www.luxcapital.com/portfolio", ("new york", "nyc", "manhattan")),
    VCFirm("Coatue", "https://www.coatue.com/portfolio", ("new york", "nyc", "manhattan")),
    VCFirm(
        "Y Combinator",
        "https://api.ycombinator.com/v0.1/companies",
        ("new york", "nyc", "manhattan", "brooklyn", "remote"),
        source="yc_api",
    ),
]


def location_keywords(location: str) -> set[str]:
    normalized = location.lower().replace(",", " ")
    tokens = {t.strip() for t in normalized.split() if len(t.strip()) > 1}
    keywords = set(tokens)
    keywords.add(normalized.strip())

    if any(k in NYC_KEYWORDS for k in keywords) or "new york" in normalized:
        keywords.update(NYC_KEYWORDS)

    return keywords


def select_vcs_for_location(location: str, max_firms: int = 12) -> list[VCFirm]:
    keywords = location_keywords(location)
    matched: list[VCFirm] = []

    for firm in VC_REGISTRY:
        if any(k in keywords for k in firm.locations):
            matched.append(firm)

    if not matched:
        matched = list(VC_REGISTRY)

    # Always include YC when searching a US metro (YC API filters client-side).
    yc = next((f for f in VC_REGISTRY if f.source == "yc_api"), None)
    if yc and yc not in matched:
        matched.append(yc)

    return matched[:max_firms]
