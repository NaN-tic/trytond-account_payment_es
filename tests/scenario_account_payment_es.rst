================
Payment Scenario
================

Imports::
    >>> import datetime
    >>> from decimal import Decimal
    >>> from proteus import Model, Wizard
    >>> from trytond.tests.tools import activate_modules
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences
    >>> today = datetime.date.today()

Install account_payment_es::

    >>> config = activate_modules('account_payment_es')

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> payable = accounts['payable']

    >>> Journal = Model.get('account.journal')
    >>> expense, = Journal.find([('code', '=', 'EXP')])

Create payment_type::

    >>> PaymentType = Model.get('account.payment.type')
    >>> payment_type = PaymentType(name='Bank Account')
    >>> payment_type.save()

Create payment journal::

    >>> PaymentJournal = Model.get('account.payment.journal')
    >>> payment_journal = PaymentJournal(name='Manual',
    ...     process_method='manual')
    >>> payment_journal.payment_type = payment_type
    >>> payment_journal.save()

Create parties::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name='Customer')
    >>> customer.save()
    >>> supplier = Party(name='Supplier')
    >>> supplier.save()

Create payable move::

    >>> Move = Model.get('account.move')
    >>> move = Move()
    >>> move.journal = expense
    >>> line = move.lines.new(account=payable, party=supplier,
    ...     credit=Decimal('50.00'))
    >>> line = move.lines.new(account=expense, debit=Decimal('50.00'))
    >>> move.click('post')

Create a payment group for the line::

    >>> Payment = Model.get('account.payment')
    >>> line, = [l for l in move.lines if l.account == payable]
    >>> pay_line = Wizard('account.move.line.create_payment_group', [line])
    >>> pay_line.form.journal = payment_journal
    >>> pay_line.form.planned_date = today
    >>> pay_line.execute('create_')
    >>> payment, = Payment.find()
    >>> payment.party == supplier
    True
    >>> payment.amount
    Decimal('50.00')
    >>> payment.state
    'processing'
