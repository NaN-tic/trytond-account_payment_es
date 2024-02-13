# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.model import ModelView
from trytond.pool import PoolMeta
from trytond.pyson import Eval
from trytond.modules.account_payment.payment import KINDS


class MoveLine(metaclass=PoolMeta):
    __name__ = 'account.move.line'

    @classmethod
    def __setup__(cls):
        super(MoveLine, cls).__setup__()
        cls._buttons.update({
                'create_payment_group': {
                    'invisible': ~Eval('payment_kind').in_(
                        list(dict(KINDS).keys())),
                    'depends': ['payment_kind'],
                    },
                })

    @classmethod
    @ModelView.button_action('account_payment_es.act_create_payment_group_line')
    def create_payment_group(cls, lines):
        pass
