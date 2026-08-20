from __future__ import annotations

from fathom.adapters.storage.database import SemanticAssetRecord
from fathom.domains.semantics.models import DomainContract, SemanticAsset
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class SqlSemanticRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def replace_contract(self, contract: DomainContract) -> None:
        with self._session_factory() as session:
            for asset in contract.assets:
                record = session.get(SemanticAssetRecord, asset.key)
                values = {
                    "kind": asset.kind.value,
                    "label": asset.label,
                    "domain": asset.domain,
                    "owner": asset.owner,
                    "definition": asset.model_dump(mode="json"),
                }
                if record is None:
                    session.add(SemanticAssetRecord(key=asset.key, **values))
                else:
                    for field, value in values.items():
                        setattr(record, field, value)
            session.commit()

    def list_assets(self) -> list[SemanticAsset]:
        with self._session_factory() as session:
            records = session.scalars(
                select(SemanticAssetRecord).order_by(
                    SemanticAssetRecord.kind, SemanticAssetRecord.label
                )
            ).all()
            return [SemanticAsset.model_validate(record.definition) for record in records]

    def search(self, query: str, limit: int = 20) -> list[SemanticAsset]:
        terms = query.casefold().strip()
        assets = self.list_assets()
        if not terms:
            return assets[:limit]
        ranked: list[tuple[int, SemanticAsset]] = []
        for asset in assets:
            haystack = " ".join(
                [asset.key, asset.label, asset.description, *asset.aliases]
            ).casefold()
            if terms in haystack:
                score = 3 if terms in {asset.key.casefold(), asset.label.casefold()} else 1
                ranked.append((score, asset))
        ranked.sort(key=lambda item: (-item[0], item[1].label))
        return [asset for _, asset in ranked[:limit]]
