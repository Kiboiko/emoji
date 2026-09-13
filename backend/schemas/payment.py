from pydantic import BaseModel
from models.order import CurrencyType
from decimal import Decimal
from typing import Optional


class CreateInvoiceRequest(BaseModel):
    """Schema for creating CryptoBot invoice"""
    order_id: str
    amount: Decimal
    currency: CurrencyType
    description: str


class InvoiceResponse(BaseModel):
    """Schema for CryptoBot invoice response"""
    invoice_id: str
    pay_url: str


class PaymentStatusResponse(BaseModel):
    """Schema for payment status check"""
    status: str
    paid: bool


class CryptoBotWebhook(BaseModel):
    """Schema for CryptoBot webhook payload"""
    update_type: str
    payload: dict
