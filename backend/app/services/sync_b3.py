from __future__ import annotations



import io
import logging
import zipfile
from collections import Counter
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




ASSET_ALIASES: dict[tuple[str, str], str] = {
    ("ALOS", "ON"): "ALOS3",
    ("ABEV", "ON"): "ABEV3",
    ("ASAI", "ON"): "ASAI3",
    ("AURE", "ON"): "AURE3",
    ("AXIA", "ON"): "AXIA3",
    ("AZZA", "ON"): "AZZA3",
    ("B3SA", "ON"): "B3SA3",
    ("BBSE", "ON"): "BBSE3",
    ("BBDC", "ON"): "BBDC3",
    ("BBDC", "PN"): "BBDC4",
    ("BRAP", "PN"): "BRAP4",
    ("BBAS", "ON"): "BBAS3",
    ("BRAV", "ON"): "BRAV3",
    ("BPAC", "UNT"): "BPAC11",
    ("CXSE", "ON"): "CXSE3",
    ("CEAB", "ON"): "CEAB3",
    ("CMIG", "PN"): "CMIG4",
    ("COGN", "ON"): "COGN3",
    ("CSMG", "ON"): "CSMG3",
    ("CPLE", "ON"): "CPLE3",
    ("CSAN", "ON"): "CSAN3",
    ("CPFE", "ON"): "CPFE3",
    ("CMIN", "ON"): "CMIN3",
    ("CURY", "ON"): "CURY3",
    ("CYRE", "ON"): "CYRE3",
    ("DIRR", "ON"): "DIRR3",
    ("EMBJ", "ON"): "EMBJ3",
    ("ENGI", "UNT"): "ENGI11",
    ("ENEV", "ON"): "ENEV3",
    ("EGIE", "ON"): "EGIE3",
    ("EQTL", "ON"): "EQTL3",
    ("FLRY", "ON"): "FLRY3",
    ("GGBR", "PN"): "GGBR4",
    ("GOAU", "PN"): "GOAU4",
    ("HAPV", "ON"): "HAPV3",
    ("HYPE", "ON"): "HYPE3",
    ("IGTI", "UNT"): "IGTI11",
    ("ISAE", "PN"): "ISAE4",
    ("ITSA", "PN"): "ITSA4",
    ("ITUB", "PN"): "ITUB4",
    ("KLBN", "UNT"): "KLBN11",
    ("RENT", "ON"): "RENT3",
    ("LREN", "ON"): "LREN3",
    ("MGLU", "ON"): "MGLU3",
    ("POMO", "PN"): "POMO4",
    ("MBRF", "ON"): "MBRF3",
    ("BEEF", "ON"): "BEEF3",
    ("MOTV", "ON"): "MOTV3",
    ("MRVE", "ON"): "MRVE3",
    ("MULT", "ON"): "MULT3",
    ("NATU", "ON"): "NATU3",
    ("PETR", "ON"): "PETR3",
    ("PETR", "PN"): "PETR4",
    ("PSSA", "ON"): "PSSA3",
    ("PRIO", "ON"): "PRIO3",
    ("RADL", "ON"): "RADL3",
    ("RDOR", "ON"): "RDOR3",
    ("RAIL", "ON"): "RAIL3",
    ("SBSP", "ON"): "SBSP3",
    ("SANB", "UNT"): "SANB11",
    ("CSNA", "ON"): "CSNA3",
    ("SMFT", "ON"): "SMFT3",
    ("SUZB", "ON"): "SUZB3",
    ("TAEE", "UNT"): "TAEE11",
    ("VIVT", "ON"): "VIVT3",
    ("TEND", "ON"): "TEND3",
    ("TIMS", "ON"): "TIMS3",
    ("TOTS", "ON"): "TOTS3",
    ("UGPA", "ON"): "UGPA3",
    ("USIM", "PNA"): "USIM5",
    ("VALE", "ON"): "VALE3",
    ("VAMO", "ON"): "VAMO3",
    ("VBBR", "ON"): "VBBR3",
    ("VIVA", "ON"): "VIVA3",
    ("WEGE", "ON"): "WEGE3",
    ("YDUQ", "ON"): "YDUQ3",



    ("ITUB", "ON"): "ITUB3",



    ("BOVA", "CI"): "BOVA11",
}




def normalize_underlying_symbol(
    raw_symbol: str,
    share_type: str,
) -> str | None:
    base_symbol = raw_symbol.strip().upper()
    share_tokens = share_type.strip().upper().split()
    share_kind = share_tokens[0] if share_tokens else ""



    if not base_symbol or not share_kind:
        return None



    return ASSET_ALIASES.get((base_symbol, share_kind))




def parse_b3_lines(lines: Iterable[str]) -> list[ParsedSeries]:
    parsed: list[ParsedSeries] = []
    unmapped: Counter[tuple[str, str]] = Counter()



    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()



        if not line or line.startswith("01|"):
            continue



        parts = line.split("|")



        if len(parts) < 18:
            continue



        option_type_raw = parts[3].strip().upper()



        if option_type_raw == "OPCOES COMPRA":
            option_type = OptionType.CALL
        elif option_type_raw == "OPCOES VENDA":
            option_type = OptionType.PUT
        else:
            continue



        underlying_raw = parts[6]
        share_type_raw = parts[7]
        option_symbol = parts[13].strip().upper()



        underlying = normalize_underlying_symbol(
            underlying_raw,
            share_type_raw,
        )



        if not underlying:
            share_tokens = share_type_raw.strip().upper().split()
            share_kind = share_tokens[0] if share_tokens else ""



            unmapped[
                (underlying_raw.strip().upper(), share_kind)
            ] += 1



            continue



        if not option_symbol:
            raise B3SyncError(
                f"Linha {line_number}: código da opção vazio "
                f"para o ativo {underlying}."
            )



        try:
            strike = Decimal(parts[16].strip())



            if not strike.is_finite() or strike < 0:
                raise ValueError("Strike inválido.")



            expiration_date = datetime.strptime(
                parts[17].strip(),
                "%Y%m%d",
            ).date()
        except (InvalidOperation, ValueError) as exc:
            raise B3SyncError(
                f"Linha {line_number}: strike ou vencimento inválido "
                f"na série {option_symbol}. Importação interrompida "
                "para não gravar valores fictícios."
            ) from exc



        parsed.append(
            ParsedSeries(
                asset_symbol=underlying,
                option_symbol=option_symbol,
                option_type=option_type,
                strike=strike,
                expiration_date=expiration_date,
                expiration_month=expiration_date.strftime("%b").upper()[:3],
            )
        )



    if unmapped:
        details = "; ".join(
            f"{base or '(vazio)'} / {kind or '(vazio)'}: {count}"
            for (base, kind), count in sorted(unmapped.items())
        )



        logger.warning(
            "Séries ignoradas por falta de alias "
            "(ativo-base / classe: quantidade): %s",
            details,
        )



    return parsed




def extract_series_text_from_zip(zip_bytes: bytes) -> str:
    if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
        preview = zip_bytes[:200].decode(
            "utf-8",
            errors="replace",
        )



        raise B3SyncError(
            "A B3 não retornou um arquivo ZIP válido. "
            f"Conteúdo inicial: {preview!r}"
        )



    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        text_members = [
            name
            for name in archive.namelist()
            if not name.endswith("/")
            and name.lower().endswith((".txt", ".csv"))
        ]



        if not text_members:
            raise B3SyncError(
                "O ZIP da B3 não contém nenhum arquivo .txt ou .csv."
            )



        preferred = [
            name
            for name in text_members
            if name.replace("\\", "/").rsplit("/", 1)[-1].lower()
            == "si_d_sede.txt"
        ]



        if preferred:
            member_name = preferred[0]
        elif len(text_members) == 1:
            member_name = text_members[0]
        else:
            raise B3SyncError(
                "O ZIP contém vários arquivos de texto, mas nenhum "
                "SI_D_SEDE.txt. Não foi possível escolher o arquivo."
            )



        return archive.read(member_name).decode("utf-8-sig")




def find_latest_local_series_file() -> Path | None:
    candidates: list[Path] = []



    for pattern in LOCAL_SERIES_PATTERNS:
        candidate = LOCAL_SERIES_DIR / pattern



        if candidate.is_file():
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



    if not parsed:
        raise B3SyncError(
            "Nenhuma série reconhecida pelos aliases foi encontrada. "
            "Nenhuma alteração foi realizada."
        )



    unique_rows: dict[str, ParsedSeries] = {}



    for row in parsed:
        previous = unique_rows.get(row.option_symbol)



        if previous is not None and previous != row:
            raise B3SyncError(
                f"A série {row.option_symbol} aparece com dados "
                "conflitantes no arquivo. Importação interrompida."
            )



        unique_rows[row.option_symbol] = row



    today = date.today()
    created = 0
    updated = 0
    deactivated = 0
    assets_created = 0
    errors: list[str] = []
    warnings: list[str] = []



    if source.upper() == "LOCAL_FALLBACK":
        warnings.append(
            "A B3 não retornou o arquivo remoto. A sincronização usou "
            "o arquivo local mais recente, que pode não estar atualizado."
        )



    try:
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



        for row in unique_rows.values():
            asset = assets.get(row.asset_symbol)



            if asset is None:
                asset = Asset(
                    symbol=row.asset_symbol,
                    name=row.asset_symbol,
                    asset_type="STOCK",
                    market="B3",
                    enabled=False,
                    tick_min=Decimal("0.01"),
                    strike_interval=Decimal("0.50"),
                    lower_range_percent=Decimal("0.00"),
                    upper_range_percent=Decimal("0.00"),
                    rtd_identifier_pattern="{symbol}",
                )



                db.add(asset)
                await db.flush()



                assets[row.asset_symbol] = asset
                assets_created += 1



            series = existing_series.get(row.option_symbol)
            should_be_active = row.expiration_date >= today



            if series is not None:
                if series.active and not should_be_active:
                    deactivated += 1



                series.asset_id = asset.id
                series.option_type = row.option_type
                series.strike = row.strike
                series.expiration_date = row.expiration_date
                series.expiration_month = row.expiration_month
                series.needs_review = row.needs_review
                series.source = source.upper()
                series.active = should_be_active



                updated += 1
            else:
                series = OptionSeries(
                    asset_id=asset.id,
                    option_symbol=row.option_symbol,
                    option_type=row.option_type,
                    strike=row.strike,
                    expiration_date=row.expiration_date,
                    expiration_month=row.expiration_month,
                    active=should_be_active,
                    source=source.upper(),
                    needs_review=row.needs_review,
                )



                db.add(series)
                existing_series[row.option_symbol] = series



                created += 1



        await db.flush()



        expired_deactivated = await deactivate_expired_series(db)
        deactivated += expired_deactivated



        executed_at = datetime.now(UTC)



        summary = {
            "created": created,
            "updated": updated,
            "deactivated": deactivated,
            "errors": errors,
            "warnings": warnings,
        }



        db.add(
            SynchronizationLog(
                event_type="sync_b3",
                message="Sincronização de séries B3 concluída.",
                payload_summary={
                    "source": source.upper(),
                    "source_url": B3_SERIES_URL,
                    "assets_created": assets_created,
                    "created": created,
                    "updated": updated,
                    "deactivated": deactivated,
                    "errors": errors,
                    "warnings": warnings,
                    "executed_at": executed_at.isoformat(),
                    "missing_series_deactivation": False,
                },
                created_at=executed_at,
            )
        )



        await db.commit()



        return summary



    except Exception:
        await db.rollback()
        raise




async def sync_from_b3(
    db: AsyncSession,
    b3_url: str | None = None,
) -> dict:
    b3_error: Exception | None = None
    series_text = ""
    source = "B3"
    request_url = (
        b3_url.strip()
        if b3_url
        else B3_SERIES_URL
    )



    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=B3_REQUEST_HEADERS,
        ) as client:
            response = await client.get(request_url)
            response.raise_for_status()



            content = response.content



            if content.startswith(b"PK"):
                series_text = extract_series_text_from_zip(content)
            else:
                text = response.text



                if (
                    "|OPCOES COMPRA|" in text
                    or "|OPCOES VENDA|" in text
                ):
                    series_text = text
                else:
                    raise B3SyncError(
                        "A B3 não retornou o arquivo de séries "
                        "autorizadas. "
                        f"Conteúdo inicial: {text[:200]!r}"
                    )

    except (
        B3SyncError,
        httpx.HTTPError,
        zipfile.BadZipFile,
        UnicodeError,
    ) as exc:
        b3_error = exc



        logger.warning(
            "Falha no download das séries B3: %s",
            exc,
        )



    if not series_text:
        local_file = find_latest_local_series_file()



        if local_file is None:
            raise B3SyncError(
                "A B3 não retornou o arquivo de séries autorizadas "
                "e não há arquivo local disponível."
            ) from b3_error



        try:
            series_text = local_file.read_text(
                encoding="utf-8-sig",
            )
        except (OSError, UnicodeError) as exc:
            raise B3SyncError(
                f"Não foi possível ler o arquivo local: {local_file}."
            ) from exc



        source = "LOCAL_FALLBACK"



        logger.warning(
            "Usando arquivo local de séries: %s",
            local_file,
        )



    return await sync_from_lines(
        db,
        series_text.splitlines(),
        source=source,
    )




async def sync_from_file(
    db: AsyncSession,
    filepath: str,
) -> dict:
    path = Path(filepath)



    if not path.is_file():
        raise FileNotFoundError(
            "Arquivo de séries não encontrado para sincronização."
        )



    try:
        series_text = path.read_text(
            encoding="utf-8-sig",
        )
    except (OSError, UnicodeError) as exc:
        raise B3SyncError(
            f"Não foi possível ler o arquivo de séries: {path}."
        ) from exc



    return await sync_from_lines(
        db,
        series_text.splitlines(),
        source="UPLOAD",
    )