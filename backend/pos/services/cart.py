"""Building an open sale (the cart): nothing is deducted from stock until
the sale is completed (pos.services.checkout)."""

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext

from catalog.models import convert_qty, sell_unit
from core import features
from core.money import ZERO, money
from inventory.stock import allocate_fefo
from pricing.models import effective_price

from ..domain import check_item_discount, share_over_batches
from ..errors import SaleError
from ..models import Sale, SaleLine


def current_price(store, product, uom=None):
    """The store's selling price today for one `uom` of `product`
    (default: its own unit) — a running promotion's price if there is
    one — or None when no price is set."""
    return effective_price(store=store, product=product, uom=uom)[0]


@transaction.atomic
def add_product(sale, *, product, qty, uom=None, unit_price=None, discount=ZERO, allow_shortfall=False):
    """Adds qty of product, in `uom` (default: the product's own unit),
    to the cart at the store's own selling price for that unit
    (pricing.Price, or a running pricing.Promotion — never a price sent
    by the till), less `discount` off the whole item. Stock is
    allocated FEFO in the product's own unit, splitting across batches
    if one alone doesn't cover it. Raises InsufficientStockError if the
    store doesn't have enough on hand. Returns the new SaleLines.

    `unit_price` is only for recording a sale the till already made
    offline (see checkout.record_offline_sale): the price the customer was
    charged then, which the cloud may have changed since. `allow_shortfall`
    (offline sales only) records the item even when the system shows
    too little stock, since the goods were sold: see allocate_fefo."""
    sale.require_status(Sale.Status.OPEN, gettext('add items to'))
    store = sale.store
    if product.entity_id != store.entity_id:
        raise SaleError(gettext("Product is not in this shop's catalog."))
    if product.is_controlled_substance and not features.is_enabled('controlled_substances_register', store=store):
        raise SaleError(gettext('{name} is a controlled drug, and {store} is not set up to sell them. An owner can switch on the controlled drugs register under Settings > Features.').format(name=product.name, store=store.name))
    sell_uom = sell_unit(product, uom)
    if sell_uom is not None and sell_uom.entity_id != product.entity_id:
        raise SaleError(gettext("Unit is not in this shop's catalog."))
    if unit_price is None:
        unit_price = current_price(store, product, sell_uom)
    if unit_price is None:
        unit = f' per {sell_uom.name}' if sell_uom else ''
        raise SaleError(
            gettext('{name} has no selling price{unit} set. Ask a manager to set one under Settings > Selling prices.').format(name=product.name, unit=unit))
    gross = money(unit_price * qty)
    discount = check_item_discount(product.name, gross, discount)

    base_qty = convert_qty(qty, sell_uom, product.uom)
    # Stock comes off only when the sale is completed, so units earlier
    # lines of this cart planned on are still on hand: reserve them.
    reserved = dict(sale.lines.filter(batch__product=product).values('batch_id')
                    .annotate(qty=Sum('qty')).values_list('batch_id', 'qty'))
    plan = allocate_fefo(store, product, base_qty, reserved=reserved, allow_shortfall=allow_shortfall)
    shares = share_over_batches(qty, base_qty, gross, discount, [batch_qty for _, batch_qty in plan])
    return [
        SaleLine.objects.create(
            sale=sale, batch=batch, qty=batch_qty, sell_uom=sell_uom, sell_qty=line_qty,
            unit_price=unit_price, discount=line_discount, amount=line_gross - line_discount,
            vat_class=product.vat_class,
        )
        for (batch, batch_qty), (line_qty, line_gross, line_discount) in zip(plan, shares)
    ]


def add_items(sale, items):
    """Adds each of `items` ({product, qty, uom?, discount?}, as the till
    sends a cart) to `sale` at today's prices."""
    for item in items:
        add_product(sale, product=item['product'], qty=item['qty'], uom=item.get('uom'),
                    discount=item.get('discount') or ZERO)


@transaction.atomic
def remove_product(sale, product):
    sale.require_status(Sale.Status.OPEN, gettext('remove items from'))
    sale.lines.filter(batch__product=product).delete()


def cancel(sale):
    """Discards a cart that was never completed. Nothing was deducted
    from stock yet, so there's nothing to reverse."""
    if sale.status != Sale.Status.OPEN:
        raise SaleError(gettext('Only an unfinished sale can be cancelled. Void a completed sale instead.'))
    sale.delete()
