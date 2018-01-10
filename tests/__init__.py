# This file is part of account_payment_es module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
try:
    from trytond.modules.account_payment_es.tests.test_account_payment_es import suite
except ImportError:
    from .test_account_payment_es import suite

__all__ = ['suite']
