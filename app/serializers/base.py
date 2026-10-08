from abc import ABC, abstractmethod
from typing import Any, List, Dict

class BaseSerializer(ABC):
    @abstractmethod
    def success(self, data: Any, message: str = "") -> Dict[str, Any]:
        pass

    @abstractmethod
    def error(self, message: str, error_type: str = "general_error", code: int = 400) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_profile(self, user: Any) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_holding(self, holding: Any) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_position(self, position: Any) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_order(self, order: Any) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_trade(self, trade: Any) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_funds(self, user: Any) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_instrument(self, inst: Any) -> Dict[str, Any]:
        pass

    @abstractmethod
    def serialize_quote(self, inst: Any) -> Dict[str, Any]:
        pass
