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



# Apelidos opcionais (caso queira forçar algum mapeamento específico)
ASSET_ALIASES = {
    # "BOVA": "BOVA11",
    # "JHSF": "JHSF3",
}




def normalize_underlying_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()


    if not symbol:
        return ""


    # O arquivo da B3 pode trazer valores como:
    # "BOVA  FM", "JHSF    /ED" ou "JHSF  FM/ED".
    # O ativo base é o primeiro token: "BOVA" ou "JHSF".
    return symbol.split()[0]




def parse_b3_lines(lines: Iterable[str]) -> list[ParsedSeries]:
    parsed: list[ParsedSeries] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("1|"):
            continue


        parts = line.split("|")
        if len(parts) < 18:
            continue


        tipo_raw = parts[3].strip().upper()
        underlying = normalize_underlying_symbol(parts[6])
        underlying = ASSET_ALIASES.get(underlying, underlying)
        option_symbol = parts[13].strip().upper()
        strike_raw = parts[16].strip()
        exp_raw = parts[17].strip()


        if not option_symbol or not underlying:
            continue


        if tipo_raw == "OPCOES COMPRA":
            otype = OptionType.CALL
        elif tipo_raw == "OPCOES VENDA":
            otype = OptionType.PUT
        else:
            continue


        try:
            strike = Decimal(strike_raw)
            expiration = datetime.strptime(exp_raw, "%Y%m%d").date()
            needs_review = False
        except Exception:
            strike = Decimal("0")
            expiration = date.today()
            needs_review = True


        parsed.append(
            ParsedSeries(
                asset_symbol=underlying,
                option_symbol=option_symbol,
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



    def find_asset_by_prefix(symbol: str):
        if symbol in assets:
            return assets[symbol]


        matches = [
            asset
            for asset_symbol, asset in assets.items()
            if asset_symbol.startswith(symbol)
        ]


        if len(matches) == 1:
            return matches[0]


        return None



    for row in parsed:
        seen_symbols.add(row.option_symbol)
        asset = find_asset_by_prefix(row.asset_symbol)


        if not asset:
            errors.append(
                f"Ativo base não cadastrado para série {row.option_symbol}: {row.asset_symbol}"
            )
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