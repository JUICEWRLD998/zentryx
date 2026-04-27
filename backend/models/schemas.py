from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Internal state models
# ---------------------------------------------------------------------------

class TrackedWallet(BaseModel):
    address: str
    label: str
    win_rate: float
    total_pnl: float
    trade_count: int


class LeaderboardEntry(BaseModel):
    rank: int
    address: str
    label: str
    total_pnl: float
    win_rate: float
    trade_count: int


# ---------------------------------------------------------------------------
# Birdeye API response models
# All fields are Optional / Any because Birdeye shapes vary by endpoint.
# We use a flexible base and strict sub-models only where we filter/compute.
# ---------------------------------------------------------------------------

class BirdeyeBase(BaseModel):
    model_config = {"extra": "allow"}


# 1. /trader/gainers-losers
class GainersLosersItem(BirdeyeBase):
    address: str | None = None
    pnl: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    trade_count: int | None = None
    win_count: int | None = None


class GainersLosersData(BirdeyeBase):
    items: list[GainersLosersItem] = Field(default_factory=list)


class GainersLosersResponse(BirdeyeBase):
    data: GainersLosersData | None = None
    success: bool = True


# 2. /wallet/v2/pnl/summary
class WalletPnLSummaryData(BirdeyeBase):
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    total_pnl: float | None = None
    win_rate: float | None = None
    trade_count: int | None = None


class WalletPnLSummary(BirdeyeBase):
    data: WalletPnLSummaryData | None = None
    success: bool = True


# 3. /wallet/v2/pnl/multiple
class WalletPnLMultipleItem(BirdeyeBase):
    address: str | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    total_pnl: float | None = None
    win_rate: float | None = None
    trade_count: int | None = None


class WalletPnLMultiple(BirdeyeBase):
    data: list[WalletPnLMultipleItem] | None = None
    success: bool = True


# 4. /wallet/v2/net-worth-details
class NetWorthToken(BirdeyeBase):
    address: str | None = None
    symbol: str | None = None
    amount: float | None = None
    value_usd: float | None = None
    unrealized_pnl: float | None = None


class WalletNetWorthDetailsData(BirdeyeBase):
    tokens: list[NetWorthToken] = Field(default_factory=list)
    total_usd: float | None = None


class WalletNetWorthDetails(BirdeyeBase):
    data: WalletNetWorthDetailsData | None = None
    success: bool = True


# 5. /wallet/v2/net-worth
class NetWorthPoint(BirdeyeBase):
    timestamp: int | None = None
    value_usd: float | None = None


class WalletNetWorthData(BirdeyeBase):
    items: list[NetWorthPoint] = Field(default_factory=list)


class WalletNetWorth(BirdeyeBase):
    data: WalletNetWorthData | None = None
    success: bool = True


# 6. /wallet/v2/balance-change
class BalanceChangeData(BirdeyeBase):
    change_usd: float | None = None
    change_pct: float | None = None


class WalletBalanceChange(BirdeyeBase):
    data: BalanceChangeData | None = None
    success: bool = True


# 7. /v1/wallet/tx_list
class WalletTx(BirdeyeBase):
    tx_hash: str | None = None
    block_time: int | None = None
    from_address: str | None = None
    to_address: str | None = None
    token_address: str | None = None
    token_amount: float | None = None
    value_usd: float | None = None
    side: str | None = None  # "buy" | "sell"


class WalletTxListData(BirdeyeBase):
    items: list[WalletTx] = Field(default_factory=list)
    total: int | None = None


class WalletTxList(BirdeyeBase):
    data: WalletTxListData | None = None
    success: bool = True


# 8. /defi/v2/tokens/top_traders
class TopTraderItem(BirdeyeBase):
    address: str | None = None
    volume: float | None = None
    trade_count: int | None = None


class TopTradersData(BirdeyeBase):
    items: list[TopTraderItem] = Field(default_factory=list)


class TopTraders(BirdeyeBase):
    data: TopTradersData | None = None
    success: bool = True


# 9. /defi/token_security
class TokenSecurityData(BirdeyeBase):
    risk_score: float | None = None
    is_honeypot: bool | None = None
    mint_authority: str | None = None
    freeze_authority: str | None = None
    top_holder_percent: float | None = None


class TokenSecurity(BirdeyeBase):
    data: TokenSecurityData | None = None
    success: bool = True


# 10. /defi/v3/price-stats/single
class PriceStatsData(BirdeyeBase):
    price: float | None = None
    price_change_24h: float | None = None
    price_change_7d: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None


class PriceStats(BirdeyeBase):
    data: PriceStatsData | None = None
    success: bool = True


# 11. /defi/v3/token/holder
class TokenHoldersData(BirdeyeBase):
    holder_count: int | None = None


class TokenHolders(BirdeyeBase):
    data: TokenHoldersData | None = None
    success: bool = True


# 12. /holder/v1/distribution
class DistributionBucket(BirdeyeBase):
    range_min: float | None = None
    range_max: float | None = None
    count: int | None = None
    percent: float | None = None


class HolderDistributionData(BirdeyeBase):
    buckets: list[DistributionBucket] = Field(default_factory=list)


class HolderDistribution(BirdeyeBase):
    data: HolderDistributionData | None = None
    success: bool = True


# 13. /smart-money/v1/token/list
class SmartMoneyToken(BirdeyeBase):
    address: str | None = None
    symbol: str | None = None
    smart_money_count: int | None = None


class SmartMoneyTokensData(BirdeyeBase):
    items: list[SmartMoneyToken] = Field(default_factory=list)


class SmartMoneyTokens(BirdeyeBase):
    data: SmartMoneyTokensData | None = None
    success: bool = True


# 14. /defi/token_overview
class TokenOverviewData(BirdeyeBase):
    address: str | None = None
    symbol: str | None = None
    name: str | None = None
    logo_uri: str | None = None
    decimals: int | None = None
    price: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    price_change_24h: float | None = None


class TokenOverview(BirdeyeBase):
    data: TokenOverviewData | None = None
    success: bool = True


# 15. /defi/v3/token/trade-data/single
class TokenTradeDataItem(BirdeyeBase):
    buy_volume_24h: float | None = None
    sell_volume_24h: float | None = None
    buy_count_24h: int | None = None
    sell_count_24h: int | None = None


class TokenTradeData(BirdeyeBase):
    data: TokenTradeDataItem | None = None
    success: bool = True


# 16. /defi/v3/token/txs
class TokenTx(BirdeyeBase):
    tx_hash: str | None = None
    block_time: int | None = None
    from_address: str | None = None
    to_address: str | None = None
    amount: float | None = None
    value_usd: float | None = None
    side: str | None = None


class TokenTxsData(BirdeyeBase):
    items: list[TokenTx] = Field(default_factory=list)
    total: int | None = None


class TokenTxs(BirdeyeBase):
    data: TokenTxsData | None = None
    success: bool = True


# 17. /defi/v3/token/exit-liquidity
class ExitLiquidityData(BirdeyeBase):
    total_liquidity_usd: float | None = None
    liquidity_depth_2pct: float | None = None


class ExitLiquidity(BirdeyeBase):
    data: ExitLiquidityData | None = None
    success: bool = True


# ---------------------------------------------------------------------------
# Mini-report: enriched token summary built from endpoints 9–17 in parallel
# ---------------------------------------------------------------------------

class TokenMiniReport(BaseModel):
    token_address: str
    security_score: float | None = None          # 0–100 from endpoint 9
    is_honeypot: bool | None = None
    smart_money_flag: bool = False               # from endpoint 13
    momentum_24h: float | None = None            # price_change_24h from endpoint 10
    holder_count: int | None = None              # from endpoint 11
    buy_sell_ratio: float | None = None          # buy_vol / (buy_vol + sell_vol) from 15
    total_liquidity_usd: float | None = None     # from endpoint 17
    symbol: str | None = None                    # from endpoint 14
    price: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
