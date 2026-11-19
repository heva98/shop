"""Selling use cases: the application layer of pos.

    cart      build an open sale: add and remove items at today's price
    checkout  complete, record (offline) and void sales
    shifts    the Z-report and closing a shift
    fiscal    getting a sale's tax receipt from the store's EFD

Views parse the request, call one of these and shape the response; the
models only hold data and what follows from it (totals, VAT). Every
function here that writes runs in a transaction and raises
pos.errors.SaleError (or another DomainError) to refuse."""
