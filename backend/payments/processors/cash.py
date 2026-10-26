from payments.interfaces import PaymentProcessor, PaymentResult


class CashProcessor(PaymentProcessor):
    """Cash needs no external confirmation — always succeeds locally,
    which is also what keeps POS fully usable while offline."""

    def charge(self, amount) -> PaymentResult:
        return PaymentResult(success=True, reference='cash')
