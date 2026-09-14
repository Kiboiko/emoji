"""
Реестр моделей.

Здесь обязаны быть импортированы ВСЕ модели проекта. Причины:

1. SQLAlchemy разрешает строковые ссылки в relationship() (например
   "ReferralTransaction") только среди уже импортированных классов. Раньше
   ReferralTransaction и Withdrawal здесь отсутствовали, и любой модуль,
   импортировавший модели выборочно (например seed.py), падал с
   InvalidRequestError при инициализации маппера User.

2. alembic/env.py делает `from models import *` — неполный список означает,
   что autogenerate не видит часть таблиц и предлагает их удалить.
"""

from .user import User
from .product import Product
from .category import Category
from .cart import CartItem
from .order import Order, OrderItem, OrderStatus, CurrencyType
from .payment import Payment, PaymentStatus
from .review import Review
from .digital_item import DigitalItem
from .referral import ReferralTransaction
from .withdrawal import Withdrawal, WithdrawalStatus
from .finance import (
    Account, AccountOwnerType, LedgerEntry, LedgerEntryType, LedgerRefType,
)
from .app_setting import AppSetting
from .subscription import (
    AccessAction, Channel, ChannelStatus, Subscription, SubscriptionAccessLog,
    SubscriptionPlan, SubscriptionStatus,
)

__all__ = [
    "User",
    "Product",
    "Category",
    "CartItem",
    "Order",
    "OrderItem",
    "OrderStatus",
    "CurrencyType",
    "Payment",
    "PaymentStatus",
    "Review",
    "DigitalItem",
    "ReferralTransaction",
    "Withdrawal",
    "WithdrawalStatus",
    "Account",
    "AccountOwnerType",
    "LedgerEntry",
    "LedgerEntryType",
    "LedgerRefType",
    "AppSetting",
    "Channel",
    "ChannelStatus",
    "SubscriptionPlan",
    "Subscription",
    "SubscriptionStatus",
    "SubscriptionAccessLog",
    "AccessAction",
]
