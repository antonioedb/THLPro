from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
UTC = timezone.utc
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, OptionSeries, OptionType, SynchronizationLog


@dataclass
class ParsedSeries:
    asset_symbol: str
    option_symbol: str
    option_type: OptionType
    strike: Decimal
    expiration_date: date
    expiration_month: str
    needs_review: bool = False


B3_SAMPLE_URL = "https://arquivos.b3.com.br/s3/indicadores/opcoes/serie_opcoes.txt"


def parse_b3_lines(lines: Iterable[str]) -> list[ParsedSeries]:
    parsed: list[ParsedSeries] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Formato simplificado para arquivo/fixture: SYMBOL;TYPE;STRIKE;EXPIRATION(YYYY-MM-DD);UNDERLYING
        parts = line.split(";")
        if len(parts) != 5:
            continue
        option_symbol, option_type, strike_raw, exp_raw, underlying = parts
        needs_review = False
        try:
            expiration = datetime.strptime(exp_raw, "%Y-%m-%d").date()
            strike = Decimal(strike_raw)
            otype = OptionType(option_type.upper())
        except Exception:  # noqa: BLE001
            needs_review = True
            expiration = date.today()
            strike = Decimal("0")
            otype = OptionType.CALL

        parsed.append(
            ParsedSeries(
                asset_symbol=underlying.upper(),
                option_symbol=option_symbol.upper(),
                option_type=otype,
                strike=strike,
                expiration_date=expiration,
                expiration_month=expiration.strftime("%b").upper()[:3],
                needs_review=needs_review,
            )
        )
    return parsed


async def sync_from_lines(db: AsyncSession, lines: Iterable[str], source: str = "B3") -> dict:
    parsed = parse_b3_lines(lines)
    created, updated, deactivated = 0, 0, 0
    errors: list[str] = []

    assets = {a.symbol: a for a in (await db.execute(select(Asset))).scalars().all()}
    existing_series = {s.option_symbol: s for s in (await db.execute(select(OptionSeries))).scalars().all()}
    seen_symbols: set[str] = set()

    for row in parsed:
        seen_symbols.add(row.option_symbol)
        asset = assets.get(row.asset_symbol)
        if not asset:
            errors.append(f"Ativo base não cadastrado para série {row.option_symbol}: {row.asset_symbol}")
            continue
        series = existing_series.get(row.option_symbol)
        if series:
            series.asset_id = asset.id
            series.option_type = row.option_type
            series.strike = row.strike
            series.expiration_date = row.expiration_date
            series.expiration_month = row.expiration_month
            series.needs_review = row.needs_review
            series.active = True
            series.source = source.upper()
            updated += 1
        else:
            db.add(
                OptionSeries(
                    asset_id=asset.id,
                    option_symbol=row.option_symbol,
                    option_type=row.option_type,
                    strike=row.strike,
                    expiration_date=row.expiration_date,
                    expiration_month=row.expiration_month,
                    active=True,
                    source=source.upper(),
                    needs_review=row.needs_review,
                )
            )
            created += 1

    for symbol, series in existing_series.items():
        if symbol not in seen_symbols and series.active:
            series.active = False
            deactivated += 1

    db.add(
        SynchronizationLog(
            event_type="sync_b3",
            message="Sincronização de séries concluída.",
            payload_summary={
                "created": created,
                "updated": updated,
                "deactivated": deactivated,
                "errors": errors,
            },
            created_at=datetime.now(UTC),
        )
    )

    await db.commit()
    return {"created": created, "updated": updated, "deactivated": deactivated, "errors": errors}


async def sync_from_file(db: AsyncSession, filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError("Arquivo de séries não encontrado para sincronização.")
    lines = path.read_text(encoding="utf-8").splitlines()
    return await sync_from_lines(db, lines, source="UPLOAD")
