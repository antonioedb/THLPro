from __future__ import annotations


import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


from app.models import Asset, OptionSeries, OptionType, SynchronizationLog



logger = logging.getLogger(__name__)


UTC = timezone.utc


B3_SERIES_URL = (
    "https://www.b3.com.br/lumis/portal/file/fileDownload.jsp"
    "?fileId=8AE490C9A134A9B101A13F33600D02CC"
)


B3_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": (
        "https://www.b3.com.br/pt_br/market-data-e-indices/"
        "servicos-de-dados/market-data/consultas/"
        "mercado-a-vista/opcoes/series-autorizadas/"
    ),
}


LOCAL_SERIES_DIR = Path("data")


LOCAL_SERIES_PATTERNS = (
    "SI_D_SEDE/SI_D_SEDE.txt",
    "SI_D_SEDE.txt",
    "series_autorizadas.txt",
)


class B3SyncError(Exception):
    pass



@dataclass
class ParsedSeries:
    asset_symbol: str
    option_symbol: str
    option_type: OptionType
    strike: Decimal
    expiration_date: date
    expiration_month: str
    needs_review: bool = False



ASSET_ALIASES: dict[str, str] = {
    # "BOVA": "BOVA11",
}



def normalize_underlying_symbol(raw_symbol: str) -> str:
    """
    A B3 pode enviar o ativo objeto como:
    'A1MD', 'A1MD FM', 'A1MD FMX', 'BOVA FM/ED', etc.


    O ativo-base é sempre o primeiro token.
    """
    symbol = raw_symbol.strip().upper()


    if not symbol:
        return ""


    return symbol.split()[0]



def parse_b3_lines(lines: Iterable[str]) -> list[ParsedSeries]:
    parsed: list[ParsedSeries] = []


    for raw_line in lines:
        line = raw_line.strip()


        if not line or line.startswith("01|"):
            continue


        parts = line.split("|")


        if len(parts) < 18:
            continue


        option_type_raw = parts[3].strip().upper()
        underlying_raw = parts[6]
        option_symbol = parts[13].strip().upper()
        strike_raw = parts[16].strip()
        expiration_raw = parts[17].strip()


        underlying = normalize_underlying_symbol(underlying_raw)
        underlying = ASSET_ALIASES.get(underlying, underlying)


        if not option_symbol or not underlying:
            continue


        if option_type_raw == "OPCOES COMPRA":
            option_type = OptionType.CALL
        elif option_type_raw == "OPCOES VENDA":
            option_type = OptionType.PUT
        else:
            continue


        needs_review = False


        try:
            strike = Decimal(strike_raw)
            expiration_date = datetime.strptime(
                expiration_raw,
                "%Y%m%d",
            ).date()
        except (InvalidOperation, ValueError):
            strike = Decimal("0")
            expiration_date = date.today()
            needs_review = True


        parsed.append(
            ParsedSeries(
                asset_symbol=underlying,
                option_symbol=option_symbol,
                option_type=option_type,
                strike=strike,
                expiration_date=expiration_date,
                expiration_month=expiration_date.strftime("%b").upper()[:3],
                needs_review=needs_review,
            )
        )


    return parsed



def extract_series_text_from_zip(zip_bytes: bytes) -> str:
    """
    Aceita apenas um ZIP válido. Se a B3 retornar HTML, erro ou bloqueio,
    a sincronização falha explicitamente.
    """
    if not zip_bytes.startswith(b"PK"):
        preview = zip_bytes[:200].decode("utf-8", errors="replace")
        raise B3SyncError(
            "A B3 não retornou um arquivo ZIP válido. "
            f"Conteúdo inicial: {preview!r}"
        )


    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        text_members = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".txt", ".csv"))
        ]


        if not text_members:
            raise B3SyncError(
                "O ZIP da B3 não contém nenhum arquivo .txt ou .csv."
            )


        preferred = [
            name
            for name in text_members
            if name.lower() == "si_d_sede.txt"
        ]


        member_name = preferred[0] if preferred else text_members[0]


        return archive.read(member_name).decode("utf-8-sig")



async def download_b3_series_text() -> str:
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=B3_REQUEST_HEADERS,
    ) as client:
        response = await client.get(B3_SERIES_URL)
        response.raise_for_status()


        content = response.content


        if content.startswith(b"PK"):
            return extract_series_text_from_zip(content)


        text = response.text


        if "|OPCOES COMPRA|" in text or "|OPCOES VENDA|" in text:
            return text


        raise B3SyncError(
            "A B3 não retornou o arquivo de séries autorizadas. "
            f"Conteúdo inicial: {text[:200]!r}"
        )



def find_latest_local_series_file() -> Path | None:
    candidates: list[Path] = []


    for pattern in LOCAL_SERIES_PATTERNS:
        candidate = LOCAL_SERIES_DIR / pattern


        if candidate.exists() and candidate.is_file():
            candidates.append(candidate)


    if not candidates:
        return None


    return max(
        candidates,
        key=lambda item: item.stat().st_mtime,
    )



async def deactivate_expired_series(db: AsyncSession) -> int:
    today = date.today()


    rows = (
        await db.execute(
            select(OptionSeries).where(
                OptionSeries.active.is_(True),
                OptionSeries.expiration_date < today,
            )
        )
    ).scalars().all()


    for series in rows:
        series.active = False


    return len(rows)



async def sync_from_lines(
    db: AsyncSession,
    lines: Iterable[str],
    source: str = "B3",
) -> dict:
    parsed = parse_b3_lines(lines)


    created = 0
    updated = 0
    deactivated = 0
    errors: list[str] = []


    assets = {
        asset.symbol: asset
        for asset in (
            await db.execute(select(Asset))
        ).scalars().all()
    }


    existing_series = {
        series.option_symbol: series
        for series in (
            await db.execute(select(OptionSeries))
        ).scalars().all()
    }


    seen_symbols: set[str] = set()


    def find_asset_by_prefix(symbol: str) -> Asset | None:
        if symbol in assets:
            return assets[symbol]


        matches = [
            asset
            for asset_symbol, asset in assets.items()
            if asset_symbol.startswith(symbol)
        ]


        return matches[0] if len(matches) == 1 else None


    for row in parsed:
        seen_symbols.add(row.option_symbol)


        asset = find_asset_by_prefix(row.asset_symbol)


        if not asset:
            asset = Asset(
                symbol=row.asset_symbol,
                name=row.asset_symbol,
                asset_type="STOCK",
                market="B3",
                tick_min=Decimal("0.01"),
                strike_interval=Decimal("0.50"),
                lower_range_percent=Decimal("0.00"),
                upper_range_percent=Decimal("0.00"),
                rtd_identifier_pattern="{symbol}",
            )


            db.add(asset)
            await db.flush()


            assets[row.asset_symbol] = asset


        series = existing_series.get(row.option_symbol)


        if series:
            series.asset_id = asset.id
            series.option_type = row.option_type
            series.strike = row.strike
            series.expiration_date = row.expiration_date
            series.expiration_month = row.expiration_month
            series.needs_review = row.needs_review
            series.source = source.upper()


            if row.expiration_date < date.today():
                series.active = False
            else:
                series.active = True


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
                    active=row.expiration_date >= date.today(),
                    source=source.upper(),
                    needs_review=row.needs_review,
                )
            )
            created += 1


    for symbol, series in existing_series.items():
        if symbol not in seen_symbols and series.active:
            series.active = False
            deactivated += 1


    expired_deactivated = await deactivate_expired_series(db)


    db.add(
        SynchronizationLog(
            event_type="sync_b3",
            message="Sincronização de séries B3 concluída.",
            payload_summary={
                "source": source.upper(),
                "source_url": B3_SERIES_URL,
                "created": created,
                "updated": updated,
                "deactivated": deactivated,
                "expired_deactivated": expired_deactivated,
                "errors": errors,
                "executed_at": datetime.now(UTC).isoformat(),
            },
            created_at=datetime.now(UTC),
        )
    )


    await db.commit()


    return {
        "created": created,
        "updated": updated,
        "deactivated": deactivated + expired_deactivated,
        "errors": errors,
    }



async def sync_from_b3(db: AsyncSession) -> dict:
    b3_error: Exception | None = None
    series_text = ""
    source = "B3"


    try:
        series_text = await download_b3_series_text()
    except Exception as exc:
        b3_error = exc


    if not series_text:
        local_file = find_latest_local_series_file()


        if not local_file:
            raise B3SyncError(
                "A B3 não retornou o arquivo de séries autorizadas "
                "e não há arquivo local disponível."
            ) from b3_error


        series_text = local_file.read_text(
            encoding="utf-8-sig",
            errors="replace",
        )
        source = "LOCAL_FALLBACK"


        logger.warning(
            "Falha ao baixar séries da B3; usando arquivo local: %s",
            local_file,
        )


    lines = series_text.splitlines()


    summary = await sync_from_lines(
        db,
        lines,
        source=source,
    )


    if source == "LOCAL_FALLBACK":
        summary["errors"].insert(
            0,
            "A B3 não retornou o arquivo remoto; a sincronização usou "
            "o arquivo local mais recente.",
        )


    return summary



async def sync_from_file(db: AsyncSession, filepath: str) -> dict:
    path = Path(filepath)


    if not path.exists():
        raise FileNotFoundError(
            "Arquivo de séries não encontrado para sincronização."
        )


    lines = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines()


    return await sync_from_lines(
        db,
        lines,
        source="UPLOAD",
    )