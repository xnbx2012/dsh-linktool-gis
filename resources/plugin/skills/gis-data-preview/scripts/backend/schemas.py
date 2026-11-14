from pydantic import BaseModel, Field
from typing import Optional


class SymbolStyle(BaseModel):
    color: str = "#ff0000"
    radius: float = 5
    weight: float = 2
    fillColor: Optional[str] = None
    fillOpacity: float = 0.6
    opacity: float = 1.0


class RendererConfig(BaseModel):
    type: str = "simple"
    symbol: SymbolStyle = Field(default_factory=SymbolStyle)
    field: Optional[str] = None
    unique_values: Optional[dict] = None
    classification_method: Optional[str] = None
    classification_breaks: Optional[list] = None


class LayerLoadRequest(BaseModel):
    geojson_path: str
    layer_name: str
    renderer: RendererConfig = Field(default_factory=RendererConfig)
