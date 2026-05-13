import os
from typing import Optional


class APIConfig:
    @staticmethod
    def get_api_key() -> Optional[str]:
        env_api_key = (
            os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("QWEN_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        masked_values = {"", "******", "None", None}
        
        if env_api_key and env_api_key not in masked_values:
            return env_api_key
        
        return None

    @staticmethod
    def get_api_key_from_config(config: dict) -> Optional[str]:
        db_api_key = config.get("api_key")
        masked_values = {"", "******", "None", None}
        
        if db_api_key and db_api_key not in masked_values:
            return db_api_key
        
        return None

    @staticmethod
    def get_base_url() -> str:
        env_base_url = (
            os.getenv("DASHSCOPE_API_BASE")
            or os.getenv("QWEN_API_BASE")
            or os.getenv("OPENAI_API_BASE")
        )
        if env_base_url and env_base_url not in {"", "******", "None", None}:
            return env_base_url
        
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @staticmethod
    def get_base_url_from_config(config: dict) -> str:
        db_base_url = config.get("api_base")
        if db_base_url:
            return db_base_url
        
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @staticmethod
    def get_combined_api_key(config: dict = None) -> Optional[str]:
        env_key = APIConfig.get_api_key()
        if env_key:
            return env_key
        
        if config:
            config_key = APIConfig.get_api_key_from_config(config)
            if config_key:
                return config_key
        
        return None

    @staticmethod
    def get_combined_base_url(config: dict = None) -> str:
        env_url = APIConfig.get_base_url()
        if env_url != "https://dashscope.aliyuncs.com/compatible-mode/v1":
            return env_url
        
        if config:
            config_url = APIConfig.get_base_url_from_config(config)
            return config_url
        
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"