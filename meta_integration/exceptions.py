import frappe


class MetaError(frappe.ValidationError):
	"""Base error for the Meta integration."""


class MetaConfigError(MetaError):
	"""The account has no usable mapping, or the company has no account."""


class MetaAPIError(MetaError):
	"""A Graph API call failed (HTTP error or an `error` object)."""
