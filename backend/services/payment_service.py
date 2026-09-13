from aiocryptopay import AioCryptoPay, Networks
from decimal import Decimal
from config import settings
from models.order import CurrencyType


class CryptoBotService:
    """Service for CryptoBot payments"""
    
    def __init__(self):
        network = Networks.TEST_NET if settings.CRYPTOBOT_TESTNET else Networks.MAIN_NET
        self.crypto_pay = AioCryptoPay(
            token=settings.CRYPTOBOT_API_TOKEN,
            network=network
        )
    
    async def create_invoice(
        self,
        amount: Decimal,
        currency: CurrencyType,
        description: str,
        payload: str = None
    ) -> dict:
        """
        Create payment invoice in CryptoBot
        Returns invoice_id and pay_url
        """
        try:
            invoice = await self.crypto_pay.create_invoice(
                asset=currency.value,  # USDT or TON
                amount=float(amount),
                description=description,
                payload=payload,
                allow_comments=False,
                allow_anonymous=False
            )
            
            return {
                "invoice_id": str(invoice.invoice_id),
                "pay_url": invoice.bot_invoice_url,
                "mini_app_url": invoice.mini_app_invoice_url,
                "web_app_url": invoice.web_app_invoice_url,
            }
        
        except Exception as e:
            raise ValueError(f"Failed to create invoice: {str(e)}")
    
    async def get_invoice_status(self, invoice_id: int) -> dict:
        """Check invoice payment status"""
        try:
            invoices = await self.crypto_pay.get_invoices(invoice_ids=[invoice_id])
            
            if not invoices:
                raise ValueError("Invoice not found")
            
            invoice = invoices[0]
            
            return {
                "invoice_id": invoice.invoice_id,
                "status": invoice.status,
                "paid": invoice.status == "paid",
                "amount": invoice.amount,
                "asset": invoice.asset,
                "paid_at": invoice.paid_at
            }
        
        except Exception as e:
            raise ValueError(f"Failed to check invoice: {str(e)}")
    
    async def close(self):
        """Close CryptoPay client"""
        await self.crypto_pay.close()


# Global instance
cryptobot_service = CryptoBotService()
