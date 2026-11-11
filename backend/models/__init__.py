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
from .promotion import ProductPromotion, PromotionInvoice
from .review import Review
from .digital_item import DigitalItem
from .referral import ReferralTransaction
from .withdrawal import Withdrawal, WithdrawalStatus
from .finance import (
    Account, AccountOwnerType, LedgerEntry, LedgerEntryType, LedgerRefType,
)
from .app_setting import AppSetting
from .admin_log import AdminAuditLog, AdminLoginLog
from .p2p import (
    Deal, DealMessage, DealStatus, ListingImage, ListingStatus, MessageDirection,
    ProductListing, SellerProfile, SellerStatus, TermsAcceptance,
)
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
    "ProductPromotion",
    "PromotionInvoice",
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
    "AdminAuditLog",
    "AdminLoginLog",
    "Channel",
    "ChannelStatus",
    "SubscriptionPlan",
    "Subscription",
    "SubscriptionStatus",
    "SubscriptionAccessLog",
    "AccessAction",
    "SellerProfile",
    "SellerStatus",
    "ProductListing",
    "ListingStatus",
    "ListingImage",
    "Deal",
    "DealStatus",
    "DealMessage",
    "MessageDirection",
    "TermsAcceptance",
]

from .market_ranking import RankingPeriod, RankingEntry
__all__ += ["RankingPeriod", "RankingEntry"]

from .telegram_publication import LargeDealConfig, TelegramPublication
from .giveaway import Giveaway, GiveawayChat, GiveawayEntry, GiveawayDrawAttempt, GiveawayPostCleanup
__all__ += ["LargeDealConfig", "TelegramPublication", "Giveaway", "GiveawayChat", "GiveawayEntry", "GiveawayDrawAttempt", "GiveawayPostCleanup"]

from .inquiry import Inquiry, InquiryMessage, InquiryMediaCleanup
from .partner import PartnerLink, PartnerAttribution, PartnerCommission
__all__ += ["Inquiry", "InquiryMessage", "InquiryMediaCleanup", "PartnerLink", "PartnerAttribution", "PartnerCommission"]
