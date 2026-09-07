// Arabica POS customization: size-picker for grouped Item Template cards.
//
// The product-card grouping itself (showing one card per Size-based drink
// template instead of one per size variant) happens server-side - see
// arabica_pos.overrides.pos.get_items, hooked in via
// override_whitelisted_methods in hooks.py. erpnext's own (unmodified)
// pos_item_selector.js renders whatever get_items returns, so once the
// server sends one merged card per template, core code already renders it
// as a single card with no change to how it's drawn.
//
// This file only adds the click behaviour for a merged card: instead of
// adding it to the cart directly (it's an Item Template, ERPNext would
// reject that with "Item ... is a template, please select one of its
// variants"), a small dialog opens with one button per size. Choosing a
// size calls cur_pos.on_cart_update(...) with the real variant item_code -
// the exact same call erpnext.PointOfSale.ItemSelector's own click handler
// makes for an ordinary card - so pricing, tax, Product Bundle behaviour,
// and stock all go through the standard POS cart flow.
//
// Deliberately generic: this file contains no item code or product name.
// A card is treated as a size-picker purely because the server marked it
// `is_grouped_template: true` and gave it `pos_variant_options`; whichever
// templates qualify (Latte, Americano, ...) is decided entirely in
// overrides/pos.py.
//
// HOW INTERCEPTION WORKS (confirmed against the installed ERPNext v16
// erpnext/selling/page/point_of_sale/pos_item_selector.js):
//
// erpnext.PointOfSale.ItemSelector's constructor runs, in order:
// prepare_dom() (creates this.$component) -> load_items_data() (the
// INITIAL render) -> bind_events() (registers the click handler) ->
// attach_shortcuts(). Two prototype methods are wrapped below, not
// replaced - both call straight through to the original after doing their
// own small bit of extra work, so core's own behaviour is unchanged for
// every card this file doesn't care about:
//
// 1. render_item_list(items) is the ONE method both the initial load
//    (load_items_data) and every subsequent search/filter (filter_items)
//    call with the full row data get_items() returned. Wrapping it lets us
//    keep our own item_code -> row lookup (this._arabica_items_by_code)
//    that is always in sync with whatever is actually on screen.
//    (This turned out to matter: core's own `this.items` is only ever set
//    inside filter_items(), NOT inside load_items_data() - so a card
//    clicked before the cashier ever searched or changed the item-group
//    filter could not be looked up via `this.items`, and the click fell
//    through to core's default add-to-cart handler. That is the exact bug
//    this rewrite fixes - see the PR notes for the full explanation.)
//
// 2. bind_events() is where core registers its own delegated click
//    handler: `this.$component.on("click", ".item-wrapper", handler)`.
//    jQuery calls multiple handlers bound to the same element/event in
//    the order they were registered, and event.stopImmediatePropagation()
//    stops any handler registered after it (on that same element) from
//    running for that event. So registering OUR delegated handler on
//    this.$component BEFORE calling the original bind_events() guarantees
//    ours runs first, and calling stopImmediatePropagation() only for a
//    grouped-template card guarantees core's own handler never runs for
//    that click - while every other card's click reaches core completely
//    untouched, in the same handler, at the same point ERPNext itself
//    wires it up.
//
// Both wraps are installed from frappe.pages["point-of-sale"].on_page_load
// (itself wrapped below) after awaiting the same "point-of-sale.bundle.js"
// asset the original on_page_load loads, and BEFORE calling the original -
// so erpnext.PointOfSale.ItemSelector is patched before any instance of it
// can possibly be constructed. No timing assumptions, no race with the
// bundle load.
//
// Loaded on the "point-of-sale" page only, via the page_js hook in
// hooks.py. No core ERPNext/Frappe file is modified - these are runtime
// prototype wraps from this file, the on-disk core files are untouched.

(function () {
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

	function patch_item_selector(ItemSelector) {
		if (ItemSelector.prototype.__arabica_patched) return;
		ItemSelector.prototype.__arabica_patched = true;

		const original_render_item_list = ItemSelector.prototype.render_item_list;
		ItemSelector.prototype.render_item_list = function (items) {
			this._arabica_items_by_code = new Map((items || []).map((item) => [item.item_code, item]));
			return original_render_item_list.call(this, items);
		};

		const original_bind_events = ItemSelector.prototype.bind_events;
		ItemSelector.prototype.bind_events = function () {
			// Registered before the original's own delegated handler on
			// the same element/event/selector, so it runs first; see the
			// file header for why that guarantees interception.
			this.$component.on("click", ".item-wrapper", (evt) => {
				const item_code = evt.currentTarget.getAttribute("data-item-code");
				const cache = this._arabica_items_by_code;
				const card_data = cache && cache.get(item_code);

				// The server, not this file, decides whether a card is a
				// grouped template - this check is the only thing gating
				// interception, and it names no product.
				if (!card_data || !card_data.is_grouped_template) return;

				evt.stopImmediatePropagation();
				open_size_dialog(card_data);
			});

			return original_bind_events.call(this);
		};
	}

	const original_on_page_load = frappe.pages["point-of-sale"].on_page_load;
	frappe.pages["point-of-sale"].on_page_load = function (wrapper) {
		frappe.require("point-of-sale.bundle.js").then(function () {
			patch_item_selector(erpnext.PointOfSale.ItemSelector);
			original_on_page_load(wrapper);
		});
	};
})();
