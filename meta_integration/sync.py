"""Sync entities (campaigns, ad sets, ads) and daily spend insights."""

import frappe
from frappe.utils import cint, flt, now_datetime

from .client import MetaClient
from .config import get_account
from .constants import STATUS_FAILED
from .exceptions import MetaAPIError
from .utils import insight_key, log_error, money, snippet, sync_window

SYNC_RUN = "Meta Sync Run"


def sync_all(company=None) -> dict:
	accounts = frappe.get_all(
		"Meta Account",
		filters={"enabled": 1, "enable_sync": 1, **({"company": company} if company else {})},
		pluck="name",
		order_by="company asc, is_default desc",
	)
	out = {"accounts": len(accounts), "results": {}}
	for name in accounts:
		try:
			out["results"][name] = sync_account(name)
		except Exception:
			log_error("Meta sync failed", f"{name}\n{frappe.get_traceback()}")
			out["results"][name] = {"status": STATUS_FAILED}
	return out


def sync_account(account: str, days=None, until=None) -> dict:
	account_doc = get_account(account)
	if not cint(account_doc.enabled) or not cint(account_doc.enable_sync):
		return {"status": "Skipped", "reason": "disabled"}
	if not account_doc.get_password("access_token", raise_exception=False):
		return {"status": "Skipped", "reason": "no token"}

	since, until = sync_window(days or account_doc.get("sync_days"), until)
	result = {
		"account": account_doc.name,
		"company": account_doc.company,
		"since": since,
		"until": until,
		"currency": None,
		"campaigns": 0,
		"ad_sets": 0,
		"ads": 0,
		"insights_new": 0,
		"insights_updated": 0,
		"insights_booked_skipped": 0,
		"errors": [],
	}

	run = frappe.get_doc(
		{
			"doctype": SYNC_RUN,
			"meta_account": account_doc.name,
			"company": account_doc.company,
			"started_on": now_datetime(),
			"status": "Running",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	try:
		client = MetaClient(account_doc)
		_refresh_account_info(account_doc, client, result)
		maps = _sync_entities(account_doc, client, result)
		_sync_insights(account_doc, client, since, until, maps, result)
		result["status"] = "Failed" if result["errors"] and not _any_change(result) else (
			"Partial" if result["errors"] else "Success"
		)
	except MetaAPIError as exc:
		result["errors"].append(str(exc)[:250])
		result["status"] = "Failed"
	except Exception as exc:
		result["errors"].append(str(exc)[:250])
		result["status"] = "Failed"
		log_error("Meta sync account failed", f"{account}\n{frappe.get_traceback()}")
	finally:
		_finish_run(run, result)

	return result


# ---------------------------------------------------------------------------
# Account info
# ---------------------------------------------------------------------------
def _refresh_account_info(account_doc, client, result):
	try:
		info = client.account_info()
	except MetaAPIError as exc:
		result["errors"].append(f"account info: {str(exc)[:150]}")
		return

	currency = (info.get("currency") or "").strip()
	result["currency"] = currency or None
	updates = {}
	if currency and currency != (account_doc.get("currency") or ""):
		updates["currency"] = currency
	if info.get("name") and info.get("name") != account_doc.get("merchant_name"):
		updates["merchant_name"] = info.get("name")
	if updates:
		frappe.db.set_value("Meta Account", account_doc.name, updates, update_modified=False)
		frappe.db.commit()


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def _sync_entities(account, client, result) -> dict:
	maps = {"campaigns": {}, "ad_sets": {}, "ads": {}}

	for field, method in (
		("campaigns", client.campaigns),
		("ad_sets", client.ad_sets),
		("ads", client.ads),
	):
		try:
			rows = method()
		except MetaAPIError as exc:
			result["errors"].append(f"{field}: {str(exc)[:150]}")
			rows = []

		for row in rows:
			try:
				name = _upsert_entity(account, field, row, maps)
				if name:
					result[field] = result.get(field, 0) + 1
			except Exception:
				log_error(
					f"Meta {field} sync failed",
					f"{account.name}: {snippet(row, 300)}\n{frappe.get_traceback()}",
				)
				result["errors"].append(f"{field} row failed")

		# Re-read so the map contains entities created before this run.
		maps[field] = _existing_map(account.name, field)

	return maps


def _existing_map(account, kind) -> dict:
	doctype, _id_field = _entity_doctype(kind)
	rows = frappe.get_all(
		doctype,
		filters={"meta_account": account},
		fields=["name", "report_to_erpnext"],
	)
	return {row.name: row.report_to_erpnext for row in rows}


def _entity_doctype(kind):
	return {
		"campaigns": ("Meta Campaign", "campaign_id"),
		"ad_sets": ("Meta Ad Set", "ad_set_id"),
		"ads": ("Meta Ad", "ad_id"),
	}[kind]


def _to_float(value):
	try:
		return flt(value) / 100.0  # budgets come in the account's minor unit
	except Exception:
		return 0.0


def _upsert_entity(account, kind, row, maps):
	doctype, id_field = _entity_doctype(kind)
	identity = str(row.get("id") or "").strip()
	if not identity:
		return None

	values = {
		"meta_account": account.name,
		"company": account.company,
		"status": row.get("status"),
		"last_synced_on": now_datetime(),
	}

	if kind == "campaigns":
		values.update(
			{
				"campaign_id": identity,
				"campaign_name": row.get("name"),
				"objective": row.get("objective"),
				"daily_budget": _to_float(row.get("daily_budget"))
				if row.get("daily_budget")
				else None,
				"lifetime_budget": _to_float(row.get("lifetime_budget"))
				if row.get("lifetime_budget")
				else None,
				"start_time": row.get("start_time"),
				"stop_time": row.get("stop_time"),
			}
		)
		name = identity
	elif kind == "ad_sets":
		campaign = str(row.get("campaign_id") or "").strip() or None
		values.update(
			{
				"ad_set_id": identity,
				"ad_set_name": row.get("name"),
				"campaign": _ensure_stub("campaigns", account, campaign, None, maps),
				"daily_budget": _to_float(row.get("daily_budget"))
				if row.get("daily_budget")
				else None,
				"lifetime_budget": _to_float(row.get("lifetime_budget"))
				if row.get("lifetime_budget")
				else None,
				"optimization_goal": row.get("optimization_goal"),
				"billing_event": row.get("billing_event"),
				"start_time": row.get("start_time"),
				"end_time": row.get("end_time"),
			}
		)
		name = identity
	else:
		ad_set = str(row.get("adset_id") or "").strip() or None
		campaign = str(row.get("campaign_id") or "").strip() or None
		values.update(
			{
				"ad_id": identity,
				"ad_name": row.get("name"),
				"ad_set": _ensure_stub("ad_sets", account, ad_set, None, maps),
				"campaign": _ensure_stub("campaigns", account, campaign, None, maps),
			}
		)
		name = identity

	if frappe.db.exists(doctype, name):
		frappe.db.set_value(doctype, name, values, update_modified=False)
	else:
		doc = frappe.new_doc(doctype)
		doc.update(values)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	maps[kind][name] = maps[kind].get(name)
	return name


def _ensure_stub(kind, account, identity, label, maps):
	"""Create a campaign/ad set/ad referenced by an insight we do not have."""
	if not identity:
		return None
	if identity in (maps.get(kind) or {}):
		return identity

	doctype, id_field = _entity_doctype(kind)
	if frappe.db.exists(doctype, identity):
		return identity

	values = {
		"meta_account": account.name,
		"company": account.company,
		id_field: identity,
		"last_synced_on": now_datetime(),
	}
	if kind == "campaigns":
		values["campaign_name"] = label or identity
	elif kind == "ad_sets":
		values["ad_set_name"] = label or identity
	else:
		values["ad_name"] = label or identity

	doc = frappe.new_doc(doctype)
	doc.update(values)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	maps.setdefault(kind, {})[identity] = 0
	return identity


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------
def _sync_insights(account, client, since, until, maps, result):
	try:
		rows = client.insights(since, until)
	except MetaAPIError as exc:
		result["errors"].append(f"insights: {str(exc)[:150]}")
		return

	existing = {}
	for row in frappe.get_all(
		"Meta Insight",
		filters={"meta_account": account.name, "date": ("between", [since, until])},
		fields=["name", "expense_entry"],
	):
		existing[row.name] = row.expense_entry

	for row in rows:
		ad_id = str(row.get("ad_id") or "").strip()
		day = str(row.get("date_start") or "")[:10]
		if not ad_id or not day:
			continue

		key = insight_key(ad_id, day)
		values = {
			"insight_key": key,
			"meta_account": account.name,
			"company": account.company,
			"date": day,
			"ad": _ensure_stub("ads", account, ad_id, row.get("ad_name"), maps),
			"ad_name": row.get("ad_name"),
			"ad_set": _ensure_stub("ad_sets", account, row.get("adset_id"), row.get("adset_name"), maps),
			"campaign": _ensure_stub(
				"campaigns", account, row.get("campaign_id"), row.get("campaign_name"), maps
			),
			"spend": money(row.get("spend")),
			"impressions": cint(row.get("impressions")),
			"clicks": cint(row.get("clicks")),
			"currency": row.get("account_currency") or account.get("currency"),
			"last_synced_on": now_datetime(),
		}

		if key in existing:
			if existing[key]:
				# Already reported: never restate a booked amount silently.
				result["insights_booked_skipped"] += 1
				frappe.db.set_value(
					"Meta Insight", key, "last_synced_on", now_datetime(), update_modified=False
				)
				continue
			frappe.db.set_value("Meta Insight", key, values, update_modified=False)
			result["insights_updated"] += 1
		else:
			try:
				doc = frappe.new_doc("Meta Insight")
				doc.update(values)
				doc.flags.ignore_permissions = True
				doc.insert(ignore_permissions=True)
				existing[key] = None
				result["insights_new"] += 1
			except Exception:
				# A concurrent run may have inserted the same ad-day first.
				existing[key] = None
				log_error(
					"Meta insight insert failed",
					f"{account.name} {key}\n{frappe.get_traceback()}",
				)

	frappe.db.commit()


# ---------------------------------------------------------------------------
def _any_change(result) -> bool:
	return any(
		result.get(key)
		for key in ("campaigns", "ad_sets", "ads", "insights_new", "insights_updated")
	)


def _finish_run(run, result):
	summary = (
		f"{result.get('since')}..{result.get('until')}: "
		f"campaigns {result.get('campaigns', 0)}, ad sets {result.get('ad_sets', 0)}, "
		f"ads {result.get('ads', 0)}, insights new {result.get('insights_new', 0)} / "
		f"updated {result.get('insights_updated', 0)}"
	)
	if result.get("insights_booked_skipped"):
		summary += f", booked rows kept as-is {result['insights_booked_skipped']}"
	if result.get("currency"):
		summary += f", currency {result['currency']}"
	if result.get("errors"):
		summary += " | errors: " + "; ".join(result["errors"][:5])

	frappe.db.set_value(
		"Meta Account",
		run.meta_account,
		{"last_sync_on": now_datetime(), "last_run_result": summary[:900]},
		update_modified=False,
	)
	frappe.db.set_value(
		SYNC_RUN,
		run.name,
		{
			"finished_on": now_datetime(),
			"status": result.get("status") or STATUS_FAILED,
			"campaigns": result.get("campaigns", 0),
			"ad_sets": result.get("ad_sets", 0),
			"ads": result.get("ads", 0),
			"insights_new": result.get("insights_new", 0),
			"insights_updated": result.get("insights_updated", 0),
			"insights_skipped": result.get("insights_booked_skipped", 0),
			"errors": len(result.get("errors") or []),
			"summary": summary[:900],
		},
		update_modified=False,
	)
	frappe.db.commit()
	result["summary"] = summary[:900]
