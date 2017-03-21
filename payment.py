## coding: utf-8
# This file is part of account_payment_es module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.wizard import Wizard, StateView, StateAction, Button
from trytond.transaction import Transaction
from decimal import Decimal

__all__ = [
    'Journal',
    'Group',
    'PayLine',
    'PayLineStart',
    'ProcessPaymentStart',
    'ProcessPayment',
    'CreatePaymentGroupStart',
    'CreatePaymentGroup',
    ]


class Journal:
    __metaclass__ = PoolMeta
    __name__ = 'account.payment.journal'
    active = fields.Boolean('Active', select=True)
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
                'required': Eval('process_method') != 'manual',
                })

    @staticmethod
    def default_active():
        return True

    @staticmethod
    def default_suffix():
        return '000'


class Group:
    __metaclass__ = PoolMeta
    __name__ = 'account.payment.group'
    join = fields.Boolean('Join lines', readonly=True,
            depends=['process_method'])
    planned_date = fields.Date('Planned Date', readonly=True,
            depends=['process_method'])
    process_method = fields.Function(fields.Char('Process Method'),
            'get_process_method')

    def get_process_method(self, name):
        return self.journal.process_method

class PayLine:
    __metaclass__ = PoolMeta
    __name__ = 'account.move.line.pay'

    def get_payment(self, line):
        payment = super(PayLine, self).get_payment(line)
        payment.description = line.description
        payment.date = line.maturity_date
        if line.origin:
            origin = line.origin.rec_name
            if not payment.description:
                payment.description = origin
            elif not origin in payment.description:
                payment.description = origin + ' ' + payment.description
        return payment


class PayLineStart:
    __metaclass__ = PoolMeta
    __name__ = 'account.move.line.pay.start'

    @classmethod
    def __setup__(cls):
        super(PayLineStart, cls).__setup__()
        cls._error_messages.update({
                'different_payment_types': ('Payment types can not be mixed. '
                    'Payment Type "%s" of line "%s" is '
                    'diferent from previous payment types "%s"')
                })

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        pool = Pool()
        Line = pool.get('account.move.line')
        Journal = pool.get('account.payment.journal')

        res = super(PayLineStart, cls).default_get(fields, with_rec_name)

        payment_type = None
        for line in Line.browse(Transaction().context.get('active_ids')):
            if not payment_type:
                payment_type = line.payment_type
            elif payment_type != line.payment_type:
                cls.raise_user_error('different_payment_types', (
                        line.payment_type and line.payment_type.rec_name or '',
                        line.rec_name, payment_type.rec_name))
        journals = Journal.search([
                ('payment_type', '=', payment_type)
                ])
        if journals and len(journals) == 1:
            res['journal'] = journals[0].id
        return res


class ProcessPaymentStart:
    __metaclass__ = PoolMeta
    __name__ = 'account.payment.process.start'
    join = fields.Boolean('Join lines', depends=['process_method'],
        help='Join payment lines of the same bank account.')
    planned_date = fields.Date('Planned Date', depends=['process_method'],
        help='Date when the payment entity must process the payment group.')
    process_method = fields.Char('Process Method')
    payments_amount = fields.Numeric('Payments Amount', digits=(16, 2),
        readonly=True)

    @classmethod
    def __setup__(cls):
        super(ProcessPaymentStart, cls).__setup__()
        cls._error_messages.update({
                'different_process_method': ('Payment process method can not '
                    'be mixed on payment groups. Payment process "%s" of line '
                    '"%s" is diferent from previous payment process "%s"')
                })

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
                    cls.raise_user_error('different_process_method', (
                            payment.journal and payment.journal.process_method
                            or '', payment.rec_name, process_method))
            payments_amount += payment.amount
        res['process_method'] = process_method
        res['payments_amount'] = payments_amount
        return res


class ProcessPayment:
    __metaclass__ = PoolMeta
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
        payments = Payment.browse(Transaction().context['active_ids'])

        if self.start.planned_date:
            for payment in payments:
                payment.date = self.start.planned_date
                payment.save()

        with Transaction().set_context(join_payments=self.start.join):
            return super(ProcessPayment, self).do_process(action)


class CreatePaymentGroupStart(ModelView):
    'Create Payment Group Start'
    __name__ = 'account.move.line.create_payment_group.start'
    journal = fields.Many2One('account.payment.journal', 'Journal',
        required=True,
        domain=[
            ('company', '=', Eval('context', {}).get('company', -1)),
            ('payment_type', '=', Eval('payment_type', -1)),
            ],
        depends=['payment_type'])
    payment_type = fields.Many2One('account.payment.type', 'Payment Type')
    join = fields.Boolean('Join lines',
        help='Join payment lines of the same bank account.')
    planned_date = fields.Date('Planned Date',
        help='Date when the payment entity must process the payment group.')
    payments_amount = fields.Numeric('Payments Amount', digits=(16, 2),
        readonly=True)

    @classmethod
    def __setup__(cls):
        super(CreatePaymentGroupStart, cls).__setup__()
        cls._error_messages.update({
                'non_posted_move': ('You can not pay line "%(line)s" because '
                    'its move "%(move)s" is not posted.'),
                'different_payment_types': ('Payment types can not be mixed on'
                    ' payment groups. Payment Type "%s" of line "%s" is '
                    'diferent from previous payment types "%s"'),
                })

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        pool = Pool()
        Line = pool.get('account.move.line')
        Journal = pool.get('account.payment.journal')

        res = super(CreatePaymentGroupStart, cls).default_get(fields,
            with_rec_name)

        payment_type = None
        payments_amount = Decimal('0.0')
        for line in Line.browse(Transaction().context.get('active_ids')):
            if line.move.state != 'posted':
                cls.raise_user_error('non_posted_move', {
                        'line': line.rec_name,
                        'move': line.move.rec_name,
                        })
            if not payment_type:
                payment_type = line.payment_type
            elif payment_type != line.payment_type:
                cls.raise_user_error('different_payment_types', (
                        line.payment_type and line.payment_type.rec_name or '',
                        line.rec_name, payment_type.rec_name))
            payments_amount += line.payment_amount
        res['payment_type'] = payment_type and payment_type.id
        res['payments_amount'] = payments_amount
        journals = Journal.search([
                ('payment_type', '=', payment_type)
                ])
        if journals and len(journals) == 1:
            res['journal'] = journals[0].id
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
        PayLine = pool.get('account.move.line.pay', type='wizard')
        ProcessPayment = pool.get('account.payment.process', type='wizard')

        session_id, _, _ = PayLine.create()
        payline = PayLine(session_id)
        payline.start.journal = self.start.journal
        payline.start.approve = True
        action, data = payline.do_pay(action)
        PayLine.delete(session_id)

        with Transaction().set_context(active_ids=data['res_id']):
            session_id, _, _ = ProcessPayment.create()
            processpayment = ProcessPayment(session_id)
            processpayment.start.join = self.start.join
            processpayment.start.planned_date = self.start.planned_date
            action, data = processpayment.do_process(action)
            ProcessPayment.delete(session_id)
            return action, data
