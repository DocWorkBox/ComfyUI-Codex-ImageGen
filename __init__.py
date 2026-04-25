from .codex_node import CodexExecImageGen


NODE_CLASS_MAPPINGS = {
    "CodexExecImageGen": CodexExecImageGen,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CodexExecImageGen": "Codex Exec ImageGen",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
