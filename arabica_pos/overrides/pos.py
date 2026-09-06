"""POS product-card grouping for Size-based Item Templates.

ERPNext's stock Point of Sale item list (erpnext.selling.page.point_of_sale
.point_of_sale.get_items) lists every sellable Item, including individual
variants (has_variants=0). It never groups variants under their template, so
an Item Template with variants - e.g. Latte with Latte-S/M/L - shows up as
one card per variant instead of one card for the drink.

This module overrides that whitelisted method (via hooks.py
override_whitelisted_methods) to call the original implementation
unmodified, then, purely by inspecting the data it returned, collapse any
Size-attribute Item Template's variants into a single card carrying
`is_grouped_template` and `pos_variant_options`. Nothing here is specific to
any one product: a template qualifies automatically if it has_variants=1 and
varies by an Item Attribute named "Size" (SIZE_ATTRIBUTE below) - Latte,
Americano, Cappuccino, or any future drink template that fits that shape is
picked up with no code change. The corresponding front-end file
(public/js/pos_custom.js) reads that same metadata generically: it does not
know any item code or product name either.

Each size option only ever uses that specific variant's own Item Price. There
is deliberately no fallback to the template's price: sizes are priced
independently, so borrowing the template's rate would silently show/charge
the wrong amount for a variant that has no Item Price configured yet.
pos_custom.js already refuses to add a variant with no rate to the cart, so
an unpriced size fails safe instead of picking up an unrelated price.

Design notes (why this isn't a rewrite of get_items):
- erpnext_get_items() is called unmodified and does all filtering: POS
  Profile item-group/warehouse restrictions, hide_unavailable_items,
  disabled/is_sales_item, search_term (including its barcode/serial path),
  pagination (start/page_length), pricing, uom preference, stock. None of
  that is duplicated here - this module only reshapes the *result*.
- The common case (a template's variants all fit on the current page - true
  for any small/medium menu) costs exactly two small, batched, indexed
  lookups total, regardless of how many templates are involved: one to find
  which returned rows are variants (Item.variant_of), one to test which of
  those templates are Size-based (Item Variant Attribute). No N+1, no extra
  work per template beyond that.
- The one case erpnext_get_items()'s pagination can genuinely break grouping
  is when page_length truncates a template's variants across the boundary,
  or a search_term happens to match only some sizes. When that happens for
  a template that IS represented on the page, _fetch_missing_variant_rows()
  fills in just the missing sizes with their own Item Price - a ~30 line
  helper, not a second copy of get_items' query/pricing/stock logic. It
  deliberately skips stock: the size dialog is text-only and never displays
  it, and the real stock check still runs standard the moment a size is
  actually added to the cart via on_cart_update.
"""

import frappe
from erpnext.selling.page.point_of_sale.point_of_sale import get_items as erpnext_get_items

# The one deliberate, business-rule constant: "Size" is the Item Attribute
# name that makes a template eligible for grouping. This is not product
# hard-coding (no item codes or names appear anywhere in this file) - it is
# the stated rule "templates that vary by Size get grouped".
SIZE_ATTRIBUTE = "Size"

# Sizes are shown in the dialog in this order when the label matches; any
# other label (a size ERPNext doesn't recognize here) is appended after,
# alphabetically.
SIZE_LABEL_ORDER = {"Small": 0, "Medium": 1, "Large": 2}


@frappe.whitelist()
def get_items(start, page_length, price_list, item_group, pos_profile, search_term=""):
	result = erpnext_get_items(
		start=start,
		page_length=page_length,
		price_list=price_list,
		item_group=item_group,
		pos_profile=pos_profile,
		search_term=search_term,
	)
	_group_size_templates(result, price_list)
	return result


def _group_size_templates(result, price_list):
	items = result.get("items") if isinstance(result, dict) else None
	if not items:
		return

	item_codes = [d["item_code"] for d in items if d.get("item_code")]
	variant_of_map = _variant_of_map(item_codes)
	if not variant_of_map:
		return

	template_codes = _eligible_templates(set(variant_of_map.values()))
	if not template_codes:
		return

	rows_by_code = {d["item_code"]: d for d in items}
	consumed_codes = set()
	grouped_cards = []

	for template_code in template_codes:
		page_variant_codes = {code for code, tmpl in variant_of_map.items() if tmpl == template_code}
		all_variant_codes = _all_variant_codes(template_code)
		missing_codes = all_variant_codes - page_variant_codes

		# Page-native rows first: they carry real stock/is_stock_item data,
		# which the merged card's own display (via core's unmodified
		# get_item_html) reads. Rows for any missing sizes are appended
		# after, used only to populate the size dialog.
		variant_rows = [rows_by_code[code] for code in page_variant_codes]
		if missing_codes:
			variant_rows += _fetch_missing_variant_rows(missing_codes, price_list)

		if not variant_rows:
			continue

		grouped_cards.append(_build_template_card(template_code, variant_rows))
		consumed_codes |= page_variant_codes

	if not grouped_cards:
		return

	items[:] = [d for d in items if d.get("item_code") not in consumed_codes]
	items.extend(grouped_cards)
	result["items"] = items


def _variant_of_map(item_codes):
	"""{item_code: template_code} for whichever of these rows are variants."""
	if not item_codes:
		return {}
	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes], "variant_of": ["is", "set"]},
		fields=["name", "variant_of"],
	)
	return {row.name: row.variant_of for row in rows}


def _eligible_templates(template_codes):
	"""Which of these templates have has_variants=1 and vary by "Size".

	"Has at least one sellable variant" (item 10's third condition) needs no
	separate check: a template only ever reaches this function because we
	already found one of its variants inside erpnext_get_items()'s own
	result, which only lists items with is_sales_item=1, disabled=0 - i.e.
	a sellable variant, by construction.
	"""
	template_codes = list(template_codes)
	if not template_codes:
		return set()

	has_variants = {
		row.name
		for row in frappe.get_all(
			"Item", filters={"name": ["in", template_codes], "has_variants": 1}, fields=["name"]
		)
	}
	if not has_variants:
		return set()

	uses_size = set(
		frappe.get_all(
			"Item Variant Attribute",
			filters={"parent": ["in", list(has_variants)], "attribute": SIZE_ATTRIBUTE},
			pluck="parent",
		)
	)
	return has_variants & uses_size


def _all_variant_codes(template_code):
	# Same sellability filter erpnext_get_items() itself applies, so a
	# disabled or non-sales variant never appears as a selectable size.
	return set(
		frappe.get_all(
			"Item",
			filters={"variant_of": template_code, "disabled": 0, "is_sales_item": 1},
			pluck="name",
		)
	)


def _fetch_missing_variant_rows(item_codes, price_list):
	"""get_items()-shaped rows for sizes that exist but weren't on the
	current page/search result (page_length truncation or a narrow search
	term). Only reached for the sizes actually missing - the common case
	(every size already on the page) never calls this. No stock lookup:
	the dialog is text-only and never shows it, and on_cart_update() still
	runs the standard stock check the moment a size is actually added.
	"""
	if not item_codes:
		return []

	item_codes = list(item_codes)
	items_by_code = {
		row.name: row
		for row in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "item_name", "description", "stock_uom", "image", "is_stock_item", "sales_uom"],
		)
	}

	prices_by_code = {}
	for row in frappe.get_all(
		"Item Price",
		filters={"item_code": ["in", item_codes], "price_list": price_list, "selling": 1},
		fields=["item_code", "price_list_rate", "currency", "uom", "batch_no"],
	):
		prices_by_code.setdefault(row.item_code, []).append(row)

	rows = []
	for code in item_codes:
		item = items_by_code.get(code)
		if not item:
			continue

		# Same uom preference erpnext_get_items() itself uses: stock uom
		# first, then sales uom, then whatever priced uom exists. Unlike
		# core, no uom-conversion step is needed afterwards: `uom` below is
		# always read straight off the matched price row, so rate and uom
		# are always a consistent pair.
		prices = prices_by_code.get(code, [])
		price = next((p for p in prices if p.uom == item.stock_uom), None)
		if not price and item.sales_uom and item.sales_uom != item.stock_uom:
			price = next((p for p in prices if p.uom == item.sales_uom), None)
		if not price and prices:
			price = prices[0]

		rows.append(
			{
				"item_code": item.name,
				"item_name": item.item_name,
				"description": item.description,
				"stock_uom": item.stock_uom,
				"item_image": item.image,
				"is_stock_item": item.is_stock_item,
				"sales_uom": item.sales_uom,
				"actual_qty": 0,
				"price_list_rate": price.price_list_rate if price else None,
				"currency": price.currency if price else None,
				"uom": price.uom if price else item.stock_uom,
				"batch_no": price.batch_no if price else None,
			}
		)
	return rows


def _build_template_card(template_code, variant_rows):
	template = frappe.get_cached_doc("Item", template_code)

	size_options = [_variant_option(row) for row in variant_rows]
	size_options.sort(key=lambda o: (SIZE_LABEL_ORDER.get(o["label"], 99), o["label"]))

	best = size_options[0] if size_options else {}

	# Start from one of the real variant rows so unrelated fields
	# (description, is_stock_item, sales_uom, ...) that get_item_html() may
	# read stay populated, then overwrite with the template's own identity
	# and a representative price.
	card = dict(variant_rows[0])
	card.update(
		{
			"item_code": template.name,
			"item_name": template.item_name,
			"item_image": template.image,
			"item_group": template.item_group,
			"price_list_rate": best.get("rate"),
			"currency": best.get("currency"),
			"is_grouped_template": True,
			"pos_variant_options": size_options,
		}
	)
	return card


def _variant_option(row):
	# Only this variant's own Item Price is ever used here - no template
	# fallback. Sizes are priced independently, so if this variant has no
	# Item Price, rate stays None and pos_custom.js refuses to add it to
	# the cart rather than charging a different size's price.
	return {
		"label": _variant_size_label(row["item_code"]),
		"item_code": row["item_code"],
		"rate": row.get("price_list_rate"),
		"currency": row.get("currency"),
		"uom": row.get("uom"),
		"stock_uom": row.get("stock_uom"),
		"batch_no": row.get("batch_no"),
		"serial_no": row.get("serial_no"),
	}


def _variant_size_label(variant_code):
	attrs = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": variant_code, "attribute": SIZE_ATTRIBUTE},
		fields=["attribute_value"],
		order_by="idx asc",
		limit=1,
	)
	return attrs[0].attribute_value if attrs else variant_code

