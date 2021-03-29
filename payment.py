# coding: utf-8
# This file is part of account_payment_es module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal

from stdnum.es.ccc import is_valid

from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.wizard import Wizard, StateView, StateAction, Button
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = [
    'BankAccount',
    'Journal',
    'Group',
    'PayLine',
    'ProcessPaymentStart',
    'ProcessPayment',
    'CreatePaymentGroupStart',
    'CreatePaymentGroup',
    ]

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
                'required': ~Eval('process_method').in_(['manual', 'sepa']),
                })

    @staticmethod
    def default_active():
        return True

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

    def set_default_payment_values(self):
        pool = Pool()
        Party = pool.get('party.party')
        Date = pool.get('ir.date')

        today = Date.today()
        values = {}
        journal = self.journal
        values['payment_journal'] = journal
        values['party'] = journal.party
        values['name'] = values['party'].name

        # Checks bank account code.
        bank_account = journal.bank_account
        if not bank_account:
            raise UserError(gettext(
                'account_payment_es.bank_account_not_defined',
                company=values['name']
            ))

        code = bank_account.get_first_other_number()
        if not code or not is_valid(code):
            raise UserError(gettext(
                'account_payment_es.wrong_bank_account',
                company=values['name']
            ))

        # Checks vat number
        tax_identifier = journal.party and journal.party.tax_identifier or None
        if not tax_identifier:
            raise UserError(gettext(
                'account_payment_es.vat_code_not_defined',
                company=values['name']))

        # Checks whether exists lines
        payments = self.payments
        if not payments:
            raise UserError(gettext('account_payment_es.no_lines'))

        values['number'] = str(self.id)
        values['payment_date'] = self.planned_date if self.planned_date \
            else today
        values['creation_date'] = today
        values['vat_code'] = tax_identifier.code
        values['suffix'] = journal.suffix
        values['company_name'] = journal.company.party.name
        values['bank_account'] = journal.bank_account.get_first_other_number()
        values['ine_code'] = journal.ine_code
        values['amount'] = 0

        values['address'] = Party.address_get(values['party'], type='invoice')
        if values['address']:
            values['street'] = values['address'].street
            values['zip'] = values['address'].zip
            values['city'] = values['address'].city
            values['subdivision'] = values['address'].subdivision or False
            values['province'] = province[values['subdivision'].code
                    if (values['subdivision']
                        and values['subdivision'].type == 'province')
                    else 'none']

        receipts = []
        if self.join:
            parties_bank_accounts = {}
            # Join all receipts of the same party and bank_account
            for payment in payments:
                key = (payment.party, payment.bank_account)
                if key not in parties_bank_accounts:
                    parties_bank_accounts[key] = [payment]
                else:
                    parties_bank_accounts[key].append(payment)
            for party_bank_account in parties_bank_accounts:
                if not party_bank_account or not party_bank_account[1]:
                    raise UserError(gettext(
                        'account_payment_es.party_without_bank_account',
                        party=party_bank_account and party_bank_account[0]
                            and party_bank_account[0].rec_name))
                amount = 0
                communication = ''
                date = False
                maturity_date = today
                create_date = False
                date_created = False
                invoices = []
                for payment in parties_bank_accounts[party_bank_account]:
                    amount += payment.amount
                    communication += '%s %s' % (payment.id,
                        payment.description)
                    if not date or date < payment.date:
                        date = payment.date
                    if payment.line:
                        if (not maturity_date
                                or maturity_date < payment.line.maturity_date):
                            maturity_date = payment.line.maturity_date
                        invoices.append(payment.line.origin)
                    if not create_date or create_date < payment.create_date:
                        create_date = payment.create_date
                    if not date_created or date_created < payment.date:
                        date_created = payment.date

                vals = {
                    'party': party_bank_account[0],
                    'bank_account':
                        party_bank_account[1].get_first_other_number(),
                    'invoices': invoices,
                    'amount': amount,
                    'communication': communication,
                    'date': date,
                    'maturity_date': maturity_date,
                    'create_date': create_date,
                    'date_created': date_created,
                    'vat_code': (party_bank_account[0].tax_identifier.code
                        if party_bank_account[0].tax_identifier else None),
                    }
                address = Party.address_get(party_bank_account[0],
                    type='invoice')
                if address:
                    vals['name'] = vals['party'].name
                    vals['address'] = address
                    vals['street'] = address.street or False
                    vals['streetbis'] = address.streetbis or False
                    vals['zip'] = address.zip or False
                    vals['city'] = address.city or False
                    vals['country'] = address.country or False
                    if vals['country']:
                        vals['country_code'] = (vals['country'].code
                            or False)
                    vals['subdivision'] = address.subdivision or False
                    vals['state'] = (vals['subdivision']
                            and vals['subdivision'].name or '')
                    vals['province'] = province[vals['subdivision'].code
                            if (vals['subdivision']
                                and vals['subdivision'].type == 'province')
                            else 'none']
                receipts.append(vals)
                values['amount'] += abs(amount)
        else:
            # Each payment is a receipt
            for payment in payments:
                if not payment.bank_account:
                    raise UserError(gettext(
                        'account_payment_es.payment_without_bank_account',
                        payment=payment.rec_name))

                party = payment.party
                amount = payment.amount
                vals = {
                    'party': party,
                    'bank_account':
                        payment.bank_account.get_first_other_number(),
                    'invoices': [payment.line and payment.line.origin or None],
                    'amount': amount,
                    'communication': '%s %s' % (payment.id,
                        payment.description),
                    'date': payment.date,
                    'maturity_date': (payment.line
                        and payment.line.maturity_date or today),
                    'create_date': payment.create_date,
                    'date_created': payment.date,
                    'vat_code': (party.tax_identifier.code
                        if party.tax_identifier else None),
                    }
                address = Party.address_get(party, type='invoice')
                if address:
                    vals['name'] = vals['party'].name
                    vals['address'] = address
                    vals['street'] = address.street or False
                    vals['streetbis'] = address.streetbis or False
                    vals['zip'] = address.zip or False
                    vals['city'] = address.city or False
                    vals['country'] = address.country or False
                    if vals['country']:
                        vals['country_code'] = vals['country'].code or False
                    vals['subdivision'] = address.subdivision or False
                    if vals['subdivision']:
                        vals['state'] = vals['subdivision'].name or ''
                    vals['province'] = province[vals['subdivision'].code
                            if (vals['subdivision']
                                and vals['subdivision'].type == 'province')
                            else 'none']
                receipts.append(vals)
                values['amount'] += abs(amount)
        if journal.require_bank_account:
            for receipt in receipts:
                if not receipt['bank_account']:
                    raise UserError(gettext(
                        'account_payment_es.customer_bank_account_not_defined',
                        party=receipt['name']))
                if not is_valid(receipt['bank_account']):
                    raise UserError(gettext(
                        'account_payment_es.wrong_party_bank_account',
                        party=receipt['name']))
        values['receipts'] = receipts
        return values

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
        payments = Payment.browse(Transaction().context['active_ids'])

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
        Payment.approve(payments)

        with Transaction().set_context(active_ids=data['res_id']):
            session_id, _, _ = ProcessPayment.create()
            processpayment = ProcessPayment(session_id)
            processpayment.start.join = self.start.join
            processpayment.start.planned_date = self.start.planned_date
            action, data = processpayment.do_process(action)
            ProcessPayment.delete(session_id)
            return action, data
