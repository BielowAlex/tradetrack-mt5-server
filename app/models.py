from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Mt5Credentials(BaseModel):
	login: int = Field(..., description="MT5 account login")
	password: str = Field(..., description="MT5 account password")
	server: str = Field(..., description="MT5 trade server name")


class Mt5TestConnectResponse(BaseModel):
	ok: bool
	message: str
	deals_count: int = 0
	sample_deals: Optional[list] = None


class Mt5GetTradesRequest(Mt5Credentials):
	from_timestamp: Optional[datetime] = Field(
		default=None,
		description="Start time for history_deals_get. If omitted, server uses last 30 days.",
	)
	to_timestamp: Optional[datetime] = Field(
		default=None,
		description="End time for history_deals_get. If omitted, server uses now.",
	)


class Mt5Deal(BaseModel):
	"""Closed deal format shared with frontend. All times in Unix seconds for exact hour display."""
	ticket: int
	position_id: int
	symbol: str
	direction: str  # "BUY" | "SELL"
	volume: float
	price: float
	profit: float
	time: int  # close time, Unix seconds
	time_open: int  # open time, Unix seconds
	commission: Optional[float] = None
	swap: Optional[float] = None


class Mt5GetTradesResponse(BaseModel):
	ok: bool
	message: str
	deals: List[Mt5Deal] = Field(default_factory=list)

