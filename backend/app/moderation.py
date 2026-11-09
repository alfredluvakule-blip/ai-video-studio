"""Basic content safeguards.

This is a keyword screen, not a classifier. It blocks clearly prohibited requests
(sexual content involving minors, non-consensual sexual content, instructions for
weapons of mass harm) and flags requests to imitate real people or copyrighted
characters so the user is reminded of their responsibility. A model-based
classifier is planned (see README).
"""
from __future__ import annotations

import re

BLOCK = [
    r"\b(child|minor|underage|kid|teen)s?\b.*\b(nude|naked|sexual|porn|explicit)",
    r"\b(nude|naked|sexual|porn|explicit)\b.*\b(child|minor|underage|kid)s?\b",
    r"\b(revenge porn|deepfake porn|non-?consensual)\b",
    r"\b(make|build|synthesi[sz]e)\b.*\b(bioweapon|nerve agent|sarin|anthrax|dirty bomb)\b",
]
WARN = [
    (r"\b(disney|pixar|marvel|pokemon|mickey mouse|harry potter|star wars)\b",
     "This looks like it references a copyrighted franchise. Only publish videos you have the rights to."),
    (r"\b(deepfake|impersonat|pretend to be)\b",
     "Do not use this tool to impersonate real people without their consent."),
]


class ContentBlocked(ValueError):
    pass


def check(*texts: str) -> list[str]:
    joined = " ".join(t for t in texts if t).lower()
    for pat in BLOCK:
        if re.search(pat, joined):
            raise ContentBlocked("This request violates the content policy and cannot be generated.")
    return [msg for pat, msg in WARN if re.search(pat, joined)]
