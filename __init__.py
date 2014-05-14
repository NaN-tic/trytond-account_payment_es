# This file is part of account_payment_es module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from .payment import *

def register():
    Pool.register(
        Journal,
        Group,
        PayLineStart,
        ProcessPaymentStart,
        CreatePaymentGroupStart,
        module='account_payment_es', type_='model')
    Pool.register(
        PayLine,
        ProcessPayment,
        CreatePaymentGroup,
        module='account_payment_es', type_='wizard')
