import datetime

from django.test import SimpleTestCase

from .periods import PeriodType, parse_period, period_id, period_label, resolve_periods, resolve_relative_period

D = datetime.date


class ParsePeriodTests(SimpleTestCase):
    def test_every_type_parses_to_a_half_open_range(self):
        cases = {
            '2026': (PeriodType.YEAR, D(2026, 1, 1), D(2027, 1, 1)),
            '2026Q4': (PeriodType.QUARTER, D(2026, 10, 1), D(2027, 1, 1)),
            '202602': (PeriodType.MONTH, D(2026, 2, 1), D(2026, 3, 1)),
            '2026W01': (PeriodType.WEEK, D(2025, 12, 29), D(2026, 1, 5)),
            '20261026': (PeriodType.DAY, D(2026, 10, 26), D(2026, 10, 27)),
        }
        for pid, (ptype, start, end) in cases.items():
            p = parse_period(pid)
            self.assertEqual((p.type, p.start, p.end), (ptype, start, end), pid)

    def test_invalid_ids_are_refused(self):
        for bad in ('2026Q5', '202613', '20260230', '2026W54', 'THIS_MONTH', '', '26'):
            with self.assertRaises(ValueError, msg=bad):
                parse_period(bad)

    def test_period_id_round_trips(self):
        day = D(2026, 1, 1)  # ISO week 1 of 2026
        self.assertEqual(period_id(PeriodType.WEEK, day), '2026W01')
        self.assertEqual(period_id(PeriodType.WEEK, D(2027, 1, 1)), '2026W53')
        self.assertEqual(period_id(PeriodType.QUARTER, D(2026, 8, 31)), '2026Q3')

    def test_labels(self):
        self.assertEqual(period_label(parse_period('202610')), 'October 2026')
        self.assertEqual(period_label(parse_period('20261026')), '26 Oct 2026')
        self.assertEqual(period_label(parse_period('2026W43')), 'Week 43 2026 (19 Oct – 25 Oct)')


class RelativePeriodTests(SimpleTestCase):
    today = D(2026, 1, 15)  # a Thursday in ISO week 3

    def resolve(self, code):
        return resolve_relative_period(code, self.today)

    def test_last_n_means_the_whole_periods_before_this_one(self):
        self.assertEqual(self.resolve('LAST_3_MONTHS'), ['202510', '202511', '202512'])
        self.assertEqual(self.resolve('LAST_QUARTER'), ['2025Q4'])
        self.assertEqual(self.resolve('LAST_7_DAYS')[0], '20260108')
        self.assertEqual(self.resolve('LAST_7_DAYS')[-1], '20260114')
        self.assertEqual(self.resolve('LAST_4_WEEKS'), ['2025W51', '2025W52', '2026W01', '2026W02'])

    def test_this_and_this_year_so_far(self):
        self.assertEqual(self.resolve('TODAY'), ['20260115'])
        self.assertEqual(self.resolve('THIS_WEEK'), ['2026W03'])
        self.assertEqual(self.resolve('MONTHS_THIS_YEAR'), ['202601'])
        self.assertEqual(resolve_relative_period('QUARTERS_THIS_YEAR', D(2026, 8, 1)), ['2026Q1', '2026Q2', '2026Q3'])
        self.assertEqual(self.resolve('LAST_YEAR'), ['2025'])

    def test_mixed_items_are_deduplicated_in_order(self):
        self.assertEqual(resolve_periods(['202601', 'THIS_MONTH', '2025'], self.today), ['202601', '2025'])
        with self.assertRaises(ValueError):
            resolve_periods(['NEXT_MONTH'], self.today)
