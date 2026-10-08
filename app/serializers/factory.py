from app.core.config import settings
from app.serializers.base import BaseSerializer
from app.serializers.format_a import FormatASerializer
from app.serializers.format_b import FormatBSerializer

def get_serializer(format_name: str = None) -> BaseSerializer:
    fmt = (format_name or settings.RESPONSE_FORMAT or "A").upper()
    if fmt == "B":
        return FormatBSerializer()
    return FormatASerializer()
