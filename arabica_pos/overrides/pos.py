"""POS product-card grouping for Item Templates with variants.

ERPNext's stock Point of Sale item list (erpnext.selling.page.point_of_sale
.point_of_sale.get_items) lists every sellable Item, including individual
variants (has_variants=0). It never groups variants under their template,
so an Item Template like "Latte" with variants Latte-S/M/L shows up as
three separate product cards.

This module overrides that whitelisted method (via hooks.py
override_whitelisted_methods) to call the original implementation
unmodified, then collapse configured variant groups into a single card
per template. The corresponding front-end file
(public/js/pos_custom.js) opens a size-picker dialog when that card is
clicked and adds the real chosen variant to the cart via the same
on_cart_update() flow ERPNext's own item cards use, so pricing, taxes,
Product Bundle behaviour and stock deduction stay standard.

Each size option only ever uses that specific variant's own Item Price.
There is deliberately no fallback to the template's price: Small,
Medium and Large are priced independently, so borrowing the template's
rate would silently show/charge the wrong amount for a variant that
simply has no Item Price configured yet. pos_custom.js already refuses
to add a variant with no rate to the cart, so an unpriced size fails
safe instead of picking up an unrelated price.

First iteration: only the "Latte" template (item_code FG-LATTE) is
grouped. Add more item codes to POS_GROUPED_TEMPLATES to extend this.
"""

import frappe
from erpnext.selling.page.point_of_sale.point_of_sale import get_items as erpnext_get_items

POS_GROUPED_TEMPLATES = ["FG-LATTE"]

# Sizes are shown in the dialog in this order when the label matches;
# anything else (a size label ERPNext doesn't recognize here) is appended
# after, alphabetically.
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
	_collapse_variant_groups(result)
	return result


def _collapse_variant_groups(result):
	items = result.get("items") if isinstance(result, dict) else None
	if not items:
		return

	for template_code in POS_GROUPED_TEMPLATES:
		variant_codes = set(frappe.get_all("Item", filters={"variant_of": template_code}, pluck="name"))
		variant_rows = [d for d in items if d.get("item_code") in variant_codes]
		if not variant_rows:
			# None of this template's variants are in this page/search
			# result (pagination or a search term excluded them) - leave
			# the result untouched.
			continue

		items = [d for d in items if d.get("item_code") not in variant_codes]
		items.append(_build_template_card(template_code, variant_rows))

	result["items"] = items


def _build_template_card(template_code, variant_rows):
	template = frappe.get_cached_doc("Item", template_code)

	size_options = [_variant_option(row) for row in variant_rows]
	size_options.sort(key=lambda o: (SIZE_LABEL_ORDER.get(o["label"], 99), o["label"]))

	best = size_options[0] if size_options else {}

	# Start from one of the real variant rows so unrelated fields
	# (description, is_stock_item, sales_uom, ...) that
	# get_item_html() may read stay populated, then overwrite with the
	# template's own identity and a representative price.
	card = dict(variant_rows[0])
	card.update(
		{
			"item_code": template.name,
			"item_name": template.item_name,
			"item_image": template.image,
			"item_group": template.item_group,
			"price_list_rate": best.get("rate"),
			"currency": best.get("currency"),
			"pos_variant_options": size_options,
		}
	)
	return card


def _variant_option(row):
	# Only this variant's own Item Price is ever used here - no template
	# fallback. Small/Medium/Large are priced independently, so if this
	# variant has no Item Price, rate stays None and pos_custom.js refuses
	# to add it to the cart rather than charging a different size's price.
	return {
		"label": _variant_size_label(row["item_code"]),
		"item_code": row["item_code"],
		"rate": row.get("price_list_rate"),
		"currency": row.get("currency"),
		"uom": row.get("uom"),
		"stock_uom": row.get("stock_uom"),
		"batch_no": row.get("batch_no"),
	}


def _variant_size_label(variant_code):
	attrs = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": variant_code},
		fields=["attribute_value"],
		order_by="idx asc",
		limit=1,
	)
	return attrs[0].attribute_value if attrs else variant_code
