"""What selling tells the rest of the system, without knowing who listens.

Modules that must react to a sale (the pharmacy's controlled drugs
register today, perhaps loyalty points or stock alerts tomorrow) connect a
receiver in their AppConfig.ready() instead of pos importing them. Selling
then depends on nothing it doesn't need, and a new module plugs in without
changing pos — the kernel/module rule of architecture.txt.

Signals are sent inside the sale's database transaction: a receiver that
raises rolls the whole sale back, so a reaction can never be half-done."""

from django.dispatch import Signal

# Sent for every sale line when its stock leaves the shelf (`returned` False:
# the sale was completed) or comes back (`returned` True: the sale was
# voided). Keyword arguments:
#   sale          the pos.Sale
#   line          the pos.SaleLine (batch and product loaded)
#   ledger_entry  the inventory.StockLedger row that moved the stock
#   user          who completed or voided the sale
#   prescription  a pos.domain.Prescription
#   returned      bool
sale_line_stock_moved = Signal()
