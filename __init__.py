# This file is part of account_payment_es module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import payment


def register():
    Pool.register(
        payment.BankAccount,
        payment.Journal,
        payment.Group,
        payment.ProcessPaymentStart,
        payment.CreatePaymentGroupStart,
        module='account_payment_es', type_='model')
    Pool.register(
        payment.PayLine,
        payment.ProcessPayment,
        payment.CreatePaymentGroup,
        module='account_payment_es', type_='wizard')
