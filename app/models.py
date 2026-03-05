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
	ticket: int
	order: int
	position_id: int
	time: datetime
	symbol: str
	volume: float
	price: float
	profit: float
	comment: Optional[str] = None


class Mt5GetTradesResponse(BaseModel):
	ok: bool
	message: str
	deals: List[Mt5Deal] = Field(default_factory=list)

