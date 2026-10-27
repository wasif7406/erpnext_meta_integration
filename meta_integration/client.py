"""Thin Meta Graph API client.

One instance per Meta Account so a token can never be used for another ad
account. Pagination follows `paging.next`; every error is logged once.
"""

import json

import frappe
import requests

from .constants import (
	AD_FIELDS,
	AD_SET_FIELDS,
	BASE_URL,
	CAMPAIGN_FIELDS,
	DEFAULT_API_VERSION,
	INSIGHT_FIELDS,
	MAX_PAGES,
	PAGE_SIZE,
)
from .exceptions import MetaAPIError
from .utils import log_error, snippet


class MetaClient:
	def __init__(self, account, timeout: int = 60):
		if isinstance(account, str):
			account = frappe.get_doc("Meta Account", account)
		self.account = account
		self.name = account.name
		self.company = account.company
		self.version = (account.get("api_version") or DEFAULT_API_VERSION).strip()
		self.ad_account_id = normalize_ad_account_id(account.get("ad_account_id"))
		self.timeout = timeout
		self._token = account.get_password("access_token", raise_exception=False)

	def _ensure_token(self):
		if not self._token:
			raise MetaAPIError(f"Meta Account {self.name} has no access token configured.")
		if not self.ad_account_id:
			raise MetaAPIError(f"Meta Account {self.name} has no Ad Account ID.")

	# -- raw requests ------------------------------------------------------
	def _get_json(self, url: str, params: dict | None = None) -> dict:
		try:
			response = requests.get(url, params=params, timeout=self.timeout)
		except Exception as exc:
			message = f"Meta request failed for {self.name}: {exc}"
			log_error("Meta API error", message)
			raise MetaAPIError(message) from exc

		try:
			payload = response.json()
		except Exception:
			payload = {"error": {"message": response.text[:400]}}

		error = payload.get("error") if isinstance(payload, dict) else None
		if error or response.status_code >= 400:
			message = (
				f"Meta API {url} failed for {self.name}: "
				f"HTTP {response.status_code} / "
				f"{(error or {}).get('type', 'error')} "
				f"{(error or {}).get('code', '')}: "
				f"{(error or {}).get('message', snippet(payload, 300))}"
			)
			log_error("Meta API error", message)
			raise MetaAPIError(message)
		return payload or {}

	def _url(self, path: str) -> str:
		return f"{BASE_URL}/{self.version}/{path.lstrip('/')}"

	def get(self, path: str, params: dict | None = None) -> dict:
		self._ensure_token()
		params = dict(params or {})
		params["access_token"] = self._token
		return self._get_json(self._url(path), params=params)

	def paged(self, path: str, params: dict | None = None) -> list:
		"""Collect every page of an edge, following `paging.next`."""
		self._ensure_token()
		params = dict(params or {})
		params["access_token"] = self._token
		params.setdefault("limit", PAGE_SIZE)

		items = []
		payload = self._get_json(self._url(path), params=params)
		items.extend(payload.get("data") or [])

		pages = 1
		next_url = (payload.get("paging") or {}).get("next")
		while next_url and pages < MAX_PAGES:
			pages += 1
			payload = self._get_json(next_url)
			items.extend(payload.get("data") or [])
			next_url = (payload.get("paging") or {}).get("next")

		if next_url:
			log_error(
				"Meta pagination truncated",
				f"{self.name}: stopped after {MAX_PAGES} pages for {path}",
			)
		return items

	# -- typed helpers -----------------------------------------------------
	def account_info(self) -> dict:
		return self.get(
			self.ad_account_id,
			params={"fields": "id,name,account_id,account_status,currency,timezone_name"},
		)

	def campaigns(self) -> list:
		return self.paged(f"{self.ad_account_id}/campaigns", params={"fields": CAMPAIGN_FIELDS})

	def ad_sets(self) -> list:
		return self.paged(f"{self.ad_account_id}/adsets", params={"fields": AD_SET_FIELDS})

	def ads(self) -> list:
		return self.paged(f"{self.ad_account_id}/ads", params={"fields": AD_FIELDS})

	def insights(self, since: str, until: str) -> list:
		"""Daily, ad-level spend for the period (one API call chain)."""
		return self.paged(
			f"{self.ad_account_id}/insights",
			params={
				"level": "ad",
				"time_increment": 1,
				"time_range": json.dumps({"since": str(since)[:10], "until": str(until)[:10]}),
				"fields": INSIGHT_FIELDS,
			},
		)


def normalize_ad_account_id(value) -> str:
	value = (value or "").strip()
	if not value:
		return ""
	return value if value.startswith("act_") else f"act_{value}"
