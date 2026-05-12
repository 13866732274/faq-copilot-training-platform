from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "咨询话术模拟训练系统"
    database_url: str = "mysql+asyncmy://chattrainer:chattrainer123456@127.0.0.1:33060/chattrainer"
    debug: bool = True
    jwt_secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 480
    super_admin_username: str = "admin"
    super_admin_password: str = "admin123456"

    dashscope_api_key: str = ""
    # FAQ 管道（批量、低频）+ quality 模式 copilot：qwen-plus 性价比最优
    dashscope_model: str = "qwen-plus"
    # Copilot 实时回复（fast/auto/balanced 模式，高频）：qwen-turbo 更快更省
    dashscope_copilot_model: str = "qwen-turbo"
    dashscope_copilot_balanced_model: str = "qwen-turbo"
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ai_scoring_rule_weight: float = 0.7
    ai_scoring_llm_weight: float = 0.3

    # WeChat bot / webhook
    bot_webhook_secret: str = ""
    faq_bot_username: str = "wechat_bot"
    faq_bot_password: str = ""
    faq_api_base: str = "http://127.0.0.1:8000/api/v1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
