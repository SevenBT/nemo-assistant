from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParameterDef:
    name: str
    type: str  # string | number | boolean | array | object
    description: str
    source: str  # config | ai | manual
    required: bool = True
    default: Optional[str] = None
    enum: list = field(default_factory=list)
    items: Optional[dict] = None  # For array type

    def to_schema_dict(self) -> dict:
        d: dict = {"type": self.type, "description": self.description}
        if self.enum:
            d["enum"] = self.enum
        if self.type == "array" and self.items:
            d["items"] = self.items
        return d


@dataclass
class ToolDefinition:
    name: str
    description: str
    script_path: str
    parameters: dict = field(default_factory=dict)  # param_name -> ParameterDef
    tool_dir: str = ""

    def to_openai_function(self) -> dict:
        properties = {}
        required_params = []
        for param_name, param_def in self.parameters.items():
            if param_def.source == "config":  # Config params are internal, not exposed to AI
                continue
            properties[param_name] = param_def.to_schema_dict()
            if param_def.required:
                required_params.append(param_name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required_params,
                },
            },
        }
