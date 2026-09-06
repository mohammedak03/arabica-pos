// Arabica POS customization: size-picker for grouped Item Template cards.
//
// The product-card grouping itself (showing one card per Size-based drink
// template instead of one per size variant) happens server-side - see
// arabica_pos.overrides.pos.get_items, hooked in via
// override_whitelisted_methods in hooks.py. erpnext's own (unmodified)
// pos_item_selector.js renders whatever get_items returns, so once the
// server sends one merged card per template, core code already renders it
// as a single card with no JS changes needed for that part.
//
// This file only adds the click behaviour for a merged card: instead of
// adding it to the cart directly (it's an Item Template, ERPNext would
// reject that), a small dialog opens with one button per size. Choosing a
// size calls cur_pos.on_cart_update(...) with the real variant item_code -
// the exact same call erpnext.PointOfSale.ItemSelector's own click handler
// makes for an ordinary card - so pricing, tax, Product Bundle behaviour,
// and stock all go through the standard POS cart flow.
//
// Deliberately generic: this file contains no item code or product name.
// A card is treated as a size-picker purely because the server marked it
// `is_grouped_template: true` and gave it `pos_variant_options`; whichever
// templates qualify (Latte today, Americano/Cappuccino/... tomorrow) is
// decided entirely in overrides/pos.py.
//
// Loaded on the "point-of-sale" page only, via the page_js hook in
// hooks.py. No core ERPNext/Frappe file is modified or monkey-patched.

(function () {
	function get_active_item_selector() {
		if (!window.cur_pos || !cur_pos.item_selector) return null;
		if (!cur_pos.item_selector.$component || !cur_pos.item_selector.$component.length) return null;
		return cur_pos.item_selector;
	}

	function find_card_data(item_selector, item_code) {
		return (item_selector.items || []).find((i) => i.item_code === item_code);
	}

	function add_variant_to_cart(variant) {
		if (!variant.rate) {
			frappe.show_alert({ message: __("Price is not set for the item."), indicator: "orange" });
			frappe.utils.play_sound("error");
			return;
		}

		// Same shape ItemSelector's own click handler passes to
		// events.item_selected -> Controller.on_cart_update. This adds a
		// real POS Invoice Item row for the chosen variant, no different
		// from clicking a normal product card.
		cur_pos.on_cart_update({
			field: "qty",
			value: "+1",
			item: {
				item_code: variant.item_code,
				batch_no: variant.batch_no,
				serial_no: variant.serial_no,
				uom: variant.uom,
				rate: variant.rate,
				stock_uom: variant.stock_uom,
			},
		});
	}

	function open_size_dialog(card_data) {
		const options = card_data.pos_variant_options || [];
		if (!options.length) {
			frappe.show_alert({ message: __("No sizes available for this item."), indicator: "orange" });
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: card_data.item_name || __("Select Size"),
			fields: [{ fieldtype: "HTML", fieldname: "arabica_pos_sizes" }],
		});

		const $wrapper = dialog.fields_dict.arabica_pos_sizes.$wrapper;
		options.forEach((variant) => {
			const $btn = $(`<button type="button" class="btn btn-default btn-block"
				style="margin-bottom: 8px; text-align: left;"></button>`).text(variant.label);
			$btn.on("click", () => {
				dialog.hide();
				add_variant_to_cart(variant);
			});
			$wrapper.append($btn);
		});

		dialog.show();
	}

	// Bound on `document` in the CAPTURE phase, which always runs before
	// any bubble-phase listener on a descendant element - including
	// ItemSelector's own `this.$component.on("click", ".item-wrapper", ...)`
	// delegate (bound in bubble phase on `.items-selector`). That makes
	// interception deterministic regardless of exactly when the POS bundle
	// finishes loading relative to this script, without needing to
	// monkey-patch erpnext.PointOfSale.ItemSelector at all.
	document.addEventListener(
		"click",
		function (evt) {
			const item_selector = get_active_item_selector();
			if (!item_selector) return;

			const $item_wrapper = evt.target.closest && evt.target.closest(".item-wrapper");
			if (!$item_wrapper) return;
			if (!item_selector.$component[0].contains($item_wrapper)) return;

			const item_code = $item_wrapper.getAttribute("data-item-code");
			const card_data = find_card_data(item_selector, item_code);

			// The server, not this file, decides whether a card is a
			// grouped template - this check is the only thing gating
			// interception, and it names no product.
			if (!card_data || !card_data.is_grouped_template) return;

			// Stop this specific click here; everything else (search,
			// other product cards, scanning, ...) is left untouched.
			evt.stopPropagation();
			evt.preventDefault();

			open_size_dialog(card_data);
		},
		true
	);
})();
