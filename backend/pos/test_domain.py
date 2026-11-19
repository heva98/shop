"""The selling rules of pos.domain, tested alone: no database, so they
run in milliseconds and pin the rules down independently of the HTTP
flows in pos/tests.py."""

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from pos.domain import (
    Prescription, check_sale_discount, check_tender, discount_over_limit, share_over_batches, split_payment, z_report,
)
from pos.errors import SaleError

D = Decimal
CASH = SimpleNamespace(name='Cash', implementation='cash')
MPESA = SimpleNamespace(name='M-Pesa', implementation='mobile_money')


def sale(total, method=CASH, credit=D('0'), vat=D('0'), discount=D('0')):
    return SimpleNamespace(
        total=D(total), vat_total=vat, discount_total=discount,
        payment_split=lambda: split_payment(method.name, method.implementation, D(total), credit),
    )


class PaymentRuleTests(SimpleTestCase):
    def test_a_credit_sale_splits_into_paid_now_and_on_account(self):
        self.assertEqual(split_payment('Cash', 'cash', D('5000'), D('3000')),
                         [('Cash', 'cash', D('2000')), ('On credit', 'credit', D('3000'))])

    def test_a_sale_wholly_on_credit_has_no_paid_part(self):
        self.assertEqual(split_payment('Cash', 'cash', D('5000'), D('5000')), [('On credit', 'credit', D('5000'))])

    def test_cash_must_cover_what_is_payable(self):
        with self.assertRaises(SaleError):
            check_tender(CASH, D('1000'), D('500'), '')
        self.assertEqual(check_tender(CASH, D('1000'), D('2000'), 'ignored'), (D('2000'), ''))

    def test_nothing_payable_in_cash_needs_no_tender(self):
        self.assertEqual(check_tender(CASH, D('0'), None, ''), (D('0'), ''))

    def test_other_methods_need_a_reference_and_take_exactly_the_amount_due(self):
        with self.assertRaises(SaleError):
            check_tender(MPESA, D('1000'), None, '  ')
        self.assertEqual(check_tender(MPESA, D('1000'), D('9999'), ' QK7 '), (D('1000'), 'QK7'))


class DiscountRuleTests(SimpleTestCase):
    def test_limit_is_a_percentage_of_the_gross(self):
        self.assertFalse(discount_over_limit(D('100'), D('1000'), D('10')))
        self.assertTrue(discount_over_limit(D('101'), D('1000'), D('10')))
        self.assertFalse(discount_over_limit(D('0'), D('1000'), D('0')))

    def test_a_sale_discount_cannot_exceed_the_total(self):
        self.assertEqual(check_sale_discount(D('10.004'), D('100')), D('10.00'))
        with self.assertRaises(SaleError):
            check_sale_discount(D('101'), D('100'))


class BatchShareTests(SimpleTestCase):
    def test_shares_add_up_exactly_to_the_item(self):
        shares = share_over_batches(D('3'), D('3'), D('1000'), D('100'), [D('1'), D('1'), D('1')])
        self.assertEqual(sum(q for q, _, _ in shares), D('3'))
        self.assertEqual(sum(g for _, g, _ in shares), D('1000'))
        self.assertEqual(sum(d for _, _, d in shares), D('100'))

    def test_a_single_batch_takes_everything(self):
        self.assertEqual(share_over_batches(D('2'), D('24'), D('36000'), D('0'), [D('24')]),
                         [(D('2'), D('36000'), D('0'))])


class PrescriptionTests(SimpleTestCase):
    def test_input_is_stripped_and_cut_to_the_stored_length(self):
        rx = Prescription.from_input('  Asha  ', None, 'R' * 100)
        self.assertEqual((rx.patient_name, rx.prescriber_name, len(rx.prescription_ref)), ('Asha', '', 64))


class ZReportTests(SimpleTestCase):
    def report(self, **overrides):
        args = dict(opening_float=D('10000'), completed=[sale('5000'), sale('3000', MPESA)],
                    voided=[sale('700')], repayments=[SimpleNamespace(payment_method=CASH, amount=D('500'))],
                    is_open=True, expected_cash_at_close=None, counted_cash=None)
        return z_report(**{**args, **overrides})

    def test_expected_cash_is_float_plus_cash_sales_plus_cash_repayments(self):
        z = self.report()
        self.assertEqual((z['cash_sales'], z['cash_repayments'], z['expected_cash']), (D('5000'), D('500'), D('15500')))
        self.assertEqual((z['sales_count'], z['gross_total'], z['void_count'], z['void_total']),
                         (2, D('8000'), 1, D('700')))

    def test_a_closed_shift_keeps_the_figure_it_was_counted_against(self):
        z = self.report(is_open=False, expected_cash_at_close=D('15000'), counted_cash=D('14900'))
        self.assertEqual((z['expected_cash'], z['changed_after_close'], z['variance']),
                         (D('15000'), D('500'), D('-100')))
