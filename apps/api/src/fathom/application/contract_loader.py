from __future__ import annotations

from pathlib import Path

import yaml
from fathom.domains.semantics.models import DomainContract


def load_contracts(directory: Path) -> list[DomainContract]:
    contracts: list[DomainContract] = []
    for path in sorted(directory.glob("**/*.yaml")):
        with path.open(encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
        contracts.append(DomainContract.model_validate(raw))
    return contracts
