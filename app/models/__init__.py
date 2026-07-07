"""Import all models so SQLAlchemy's registry sees them for create_all()."""
from app.models.user import User
from app.models.prescription import Prescription, Detection
from app.models.inventory import InventoryItem
from app.models.demand import DemandEvent, RestockRequest
from app.models.analytics import VoteEvent, SearchEvent, StockEvent
from app.models.guest import GuestUsage

__all__ = [
    "User", "Prescription", "Detection", "InventoryItem",
    "DemandEvent", "RestockRequest", "VoteEvent", "SearchEvent", "StockEvent",
    "GuestUsage",
]
