from typing import Literal

AtsType = Literal[
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "teamtailor",
    "workday",
    "icims",
    "taleo",
    "successfactors",
    "smartrecruiters",
    "jobvite",
    "rippling",
    "bamboohr",
]

FETCHABLE_ATS: frozenset[AtsType] = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "workable",
        "teamtailor",
        "workday",
        "icims",
        "taleo",
        "successfactors",
        "smartrecruiters",
        "jobvite",
        "rippling",
        "bamboohr",
    }
)
