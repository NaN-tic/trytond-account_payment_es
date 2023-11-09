# coding: utf-8
# This file is part of account_payment_es module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
from itertools import groupby
from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.wizard import Wizard, StateView, StateAction, Button
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError

province = {
    'none': '',
    'ES-VI': '01',
    'ES-AB': '02',
    'ES-A': '03',
    'ES-AL': '04',
    'ES-AV': '05',
    'ES-BA': '06',
    'ES-PM': '07',
    'ES-B': '08',
    'ES-BU': '09',
    'ES-CC': '10',
    'ES-CA': '11',
    'ES-CS': '12',
    'ES-CR': '13',
    'ES-CO': '14',
    'ES-C': '15',
    'ES-CU': '16',
    'ES-GI': '17',
    'ES-GR': '18',
    'ES-GU': '19',
    'ES-SS': '20',
    'ES-H': '21',
    'ES-HU': '22',
    'ES-J': '23',
    'ES-LE': '24',
    'ES-L': '25',
    'ES-LO': '26',
    'ES-LU': '27',
    'ES-M': '28',
    'ES-MA': '29',
    'ES-MU': '30',
    'ES-NA': '31',
    'ES-OR': '32',
    'ES-O': '33',
    'ES-P': '34',
    'ES-GC': '35',
    'ES-PO': '36',
    'ES-SA': '37',
    'ES-TF': '38',
    'ES-S': '39',
    'ES-SG': '40',
    'ES-SE': '41',
    'ES-SO': '42',
    'ES-T': '43',
    'ES-TE': '44',
    'ES-TO': '45',
    'ES-V': '46',
    'ES-VA': '47',
    'ES-BI': '48',
    'ES-ZA': '49',
    'ES-Z': '50',
    'ES-CE': '51',
    'ES-ML': '52',
    }


class BankAccount(metaclass=PoolMeta):
    __name__ = 'bank.account'

    def get_first_other_number(self):
        iban = None
        for number in self.numbers:
            if number.type == 'other':
                return number.number
            elif not iban and number.type == 'iban':
                iban = number.number
        if iban:
            return iban[4:].replace(' ', '')
        return None


class Journal(metaclass=PoolMeta):
    __name__ = 'account.payment.journal'
    require_bank_account = fields.Boolean('Require bank account',
        help=('If your bank allows you to send payment groups without the bank'
            ' account info, you may disable this option.'))
    suffix = fields.Char('Suffix', states={
            'required': Eval('process_method') != 'none'
            })
    ine_code = fields.Char('INE code')

    @classmethod
    def __setup__(cls):
        super(Journal, cls).__setup__()
        cls.party.states.update({
                'required': ~Eval('process_method').in_(['manual', 'sepa']),
                })

    @staticmethod
    def default_suffix():
        return '000'


class Group(metaclass=PoolMeta):
    __name__ = 'account.payment.group'
    join = fields.Boolean('Join lines', readonly=True,
        depends=['process_method'])
    planned_date = fields.Date('Planned Date', readonly=True,
        depends=['process_method'])
    process_method = fields.Function(fields.Char('Process Method'),
        'get_process_method')

    @classmethod
    def __setup__(cls):
        super(Group, cls).__setup__()
        cls._order.insert(0, ('number', 'DESC'))

    def get_process_method(self, name):
        return self.journal.process_method

    def attach_file(self, data):
        IrAttachment = Pool().get('ir.attachment')
        journal = self.journal
        values = {
            'name': '%s_%s_%s' % (gettext('account_payment_es.remittance'),
                journal.process_method, self.reference),
            'type': 'data',
            'data': data,
            'resource': '%s' % (self),
            }
        IrAttachment.create([values])


class PayLine(metaclass=PoolMeta):
    __name__ = 'account.move.line.pay'

    def get_payment(self, line, journals):
        payment = super(PayLine, self).get_payment(line, journals)
        payment.description = line.description
        if line.maturity_date:
            payment.date = line.maturity_date
        if line.origin:
            origin = line.origin.rec_name
            if not payment.description:
                payment.description = origin
            elif origin not in payment.description:
                payment.description = origin + ' ' + payment.description
        return payment


class Payment(metaclass=PoolMeta):
    __name__ = 'account.payment'

    @classmethod
    def join_payment_keyfunc(cls, x):
        return (x.currency, x.party)

    @property
    def get_join_description(self):
        # get_sepa_end_to_end_id return self.id from account_payment_sepa_es module
        return str(self.id)

    @classmethod
    def get_join_payments(cls, payments):
        new_payments = []
        payments = sorted(payments, key=cls.join_payment_keyfunc)
        for key, grouped in groupby(payments, cls.join_payment_keyfunc):
            amount = 0
            date = None
            payment_description = []
            for payment in grouped:
                amount += payment.amount
                payment_description.append(payment.get_join_description)
                if not date or payment.date > date:
                    date = payment.date

            payment.amount = amount
            payment.line = None
            payment.description = ','.join(payment_description)[:35]
            payment.date = date
            new_payments.append(payment)
        return new_payments

    @classmethod
    def process(cls, payments, group):
        # in case join payments in the context, group payments in one record
        if Transaction().context.get('join_payments'):
            payments = cls.get_join_payments(payments)
            cls.save(payments)
        return super().process(payments, group)


class ProcessPaymentStart(metaclass=PoolMeta):
    __name__ = 'account.payment.process.start'
    join = fields.Boolean('Join lines', depends=['process_method'],
        help='Join payment lines of the same bank account.')
    planned_date = fields.Date('Planned Date', depends=['process_method'],
        help='Date when the payment entity must process the payment group.')
    process_method = fields.Char('Process Method')
    payments_amount = fields.Numeric('Payments Amount', digits=(16, 2),
        readonly=True)

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        pool = Pool()
        Payment = pool.get('account.payment')

        res = super(ProcessPaymentStart, cls).default_get(fields,
            with_rec_name)

        process_method = False
        payments_amount = Decimal('0.0')
        for payment in Payment.browse(Transaction().context['active_ids']):
            if not process_method:
                process_method = payment.journal.process_method
            else:
                if process_method != payment.journal.process_method:
                    raise UserError(gettext(
                        'account_payment_es.different_process_method',
                            process=(payment.journal and
                                payment.journal.process_method
                                or ''),
                            payment=payment.rec_name,
                            pprocess=process_method))
            payments_amount += payment.amount
        res['process_method'] = process_method
        res['payments_amount'] = payments_amount
        return res


class ProcessPayment(metaclass=PoolMeta):
    __name__ = 'account.payment.process'

    def _group_payment_key(self, payment):
        res = list(super(ProcessPayment, self)._group_payment_key(payment))
        res.append(tuple(['join', self.start.join]))
        if self.start.planned_date:
            res.append(tuple(['planned_date', self.start.planned_date]))
        return tuple(res)

    def do_process(self, action):
        pool = Pool()
        Payment = pool.get('account.payment')

        payments = self.records

        if self.start.planned_date:
            for payment in payments:
                payment.date = self.start.planned_date
            Payment.save(payments)

        with Transaction().set_context(join_payments=self.start.join):
            return super(ProcessPayment, self).do_process(action)


class CreatePaymentGroupStart(ModelView):
    'Create Payment Group Start'
    __name__ = 'account.move.line.create_payment_group.start'
    journal = fields.Many2One('account.payment.journal', 'Journal',
        required=True,
        domain=[
            ('company', '=', Eval('context', {}).get('company', -1)),
            ])
    join = fields.Boolean('Join lines',
        help='Join payment lines of the same bank account.')
    planned_date = fields.Date('Planned Date',
        help='Date when the payment entity must process the payment group.')
    payments_amount = fields.Numeric('Payments Amount', digits=(16, 2),
        readonly=True)

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        pool = Pool()
        Line = pool.get('account.move.line')
        res = super(CreatePaymentGroupStart, cls).default_get(fields,
            with_rec_name)

        payments_amount = Decimal('0.0')
        for line in Line.browse(Transaction().context.get('active_ids', [])):
            if line.move.state != 'posted':
                raise UserError(gettext('account_payment_es.non_posted_move',
                        line=line.rec_name,
                        move=line.move.rec_name,
                        ))
            payments_amount += line.payment_amount or Decimal(0)
        res['payments_amount'] = payments_amount
        return res


class CreatePaymentGroup(Wizard):
    'Create Payment Group'
    __name__ = 'account.move.line.create_payment_group'
    start = StateView('account.move.line.create_payment_group.start',
        'account_payment_es.move_line_create_payment_group_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Create', 'create_', 'tryton-ok', default=True),
            ])
    create_ = StateAction('account_payment.act_payment_group_form')

    def do_create_(self, action):
        pool = Pool()
        Payment = pool.get('account.payment')
        PayLine = pool.get('account.move.line.pay', type='wizard')
        ProcessPayment = pool.get('account.payment.process', type='wizard')

        session_id, _, _ = PayLine.create()
        payline = PayLine(session_id)
        payline.start.date = self.start.planned_date
        payline.ask_journal.journal = self.start.journal
        payline.ask_journal.journals = [self.start.journal]
        action, data = payline.do_pay(action)
        PayLine.delete(session_id)
        payments = Payment.browse(data['res_id'])
        # merge_request779 [account_payment] Warn when submitting, approving or proceeding payment with reconciled line
        if hasattr(Payment, '_check_reconciled'):
            Payment._check_reconciled(payments)
        Payment.submit(payments)
        # allow create groups from receivable issues11190
        to_approve = [payment for payment in payments
            if payment.kind != 'receivable']
        if to_approve:
            Payment.approve(to_approve)

        with Transaction().set_context(active_id=None, active_ids=data['res_id'],
                active_model='account.payment'):
            session_id, _, _ = ProcessPayment.create()
            processpayment = ProcessPayment(session_id)
            processpayment.start.join = self.start.join
            processpayment.start.planned_date = self.start.planned_date
            action, data = processpayment.do_process(action)
            ProcessPayment.delete(session_id)
            return action, data
