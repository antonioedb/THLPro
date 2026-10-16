from datetime import date, datetime
from decimal import Decimal


from pydantic import BaseModel, ConfigDict, Field



class AssetBase(BaseModel):
    symbol: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=255)
    asset_type: str = Field(min_length=2, max_length=50)
    market: str = Field(min_length=2, max_length=50)
    enabled: bool = True
    tick_min: Decimal = Decimal("0.01")
    strike_interval: Decimal = Decimal("1")
    lower_range_percent: Decimal = Decimal("10")
    upper_range_percent: Decimal = Decimal("10")
    rtd_identifier_pattern: str = "{SYMBOL}{CODE}_B_0"
    source: str = "MANUAL"



class AssetCreate(AssetBase):
    pass



class AssetUpdate(BaseModel):
    symbol: str | None = Field(default=None, min_length=2, max_length=30)
    name: str | None = Field(default=None, min_length=2, max_length=255)
    asset_type: str | None = Field(default=None, min_length=2, max_length=50)
    market: str | None = Field(default=None, min_length=2, max_length=50)
    enabled: bool | None = None
    tick_min: Decimal | None = None
    strike_interval: Decimal | None = None
    lower_range_percent: Decimal | None = None
    upper_range_percent: Decimal | None = None
    rtd_identifier_pattern: str | None = None



class AssetOut(AssetBase):
    model_config = ConfigDict(from_attributes=True)


    id: int
    created_at: datetime
    updated_at: datetime



class StrikeCoverageOut(BaseModel):
    """
    Cobertura de um strike dentro dos vencimentos mensais escolhidos.


    monthly_expirations representa quantos vencimentos mensais compõem a
    curva atual do ativo.


    call_expirations e put_expirations indicam em quantos desses vencimentos
    existe uma série ativa do lado correspondente.


    complete_pairs indica em quantos vencimentos existem simultaneamente
    CALL e PUT para o mesmo strike.
    """


    strike: Decimal
    monthly_expirations: int
    call_expirations: int
    put_expirations: int
    complete_pairs: int
    monthly_dates: list[date] = Field(default_factory=list)


    @property
    def has_full_call_coverage(self) -> bool:
        return (
            self.monthly_expirations > 0
            and self.call_expirations == self.monthly_expirations
        )


    @property
    def has_full_put_coverage(self) -> bool:
        return (
            self.monthly_expirations > 0
            and self.put_expirations == self.monthly_expirations
        )


    @property
    def has_full_pair_coverage(self) -> bool:
        return (
            self.monthly_expirations > 0
            and self.complete_pairs == self.monthly_expirations
        )



class StrikeListResponse(BaseModel):
    asset: str
    spot_price: Decimal | None
    range_low: Decimal | None
    range_high: Decimal | None


    # Campo legado mantido para não quebrar o select atual do frontend.
    strikes: list[Decimal]


    # Nova lista com cobertura de CALL/PUT nos vencimentos mensais.
    strike_coverage: list[StrikeCoverageOut] = Field(default_factory=list)


    # Datas mensais usadas no cálculo da cobertura.
    monthly_expirations: list[date] = Field(default_factory=list)


    # Strike recomendado: o mais próximo do spot entre os strikes com
    # cobertura completa de CALL e PUT em todos os vencimentos mensais.
    recommended_strike: Decimal | None = None


    data_avail: bool
    warning: str | None = None