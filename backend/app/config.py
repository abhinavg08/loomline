from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import os

ROOT = Path(__file__).resolve().parents[2]
TENANTS = {"alpha": "loom_t_alpha", "beta": "loom_t_beta"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.environ.get('LOOM_ENV_FILE',ROOT / '.env'), extra='ignore',hide_input_in_errors=True)
    falkordb_host: str = '127.0.0.1'
    falkordb_port: int = 6379
    falkordb_password: str = Field(default='',repr=False)
    loom_graph_namespace: str = Field(default='demo',pattern=r'^(demo|(?:test|bench|release)_[a-f0-9]{16})$')
    loom_auth_file: str = '.secrets/auth.json'
    nvidia_base_url: str = 'https://integrate.api.nvidia.com/v1'
    nvidia_model: str = ''
    nvidia_investigator_api_key: str = Field(default='',repr=False)
    nvidia_verifier_api_key: str = Field(default='',repr=False)
    nvidia_coordinator_api_key: str = Field(default='',repr=False)
    nvidia_api_key: str = Field(default='',repr=False)
    nvidia_live_enabled: bool = False
    nvidia_global_rpm_limit: int = 30
    nvidia_max_concurrent_requests: int = 3
    nvidia_request_timeout_seconds: int = 60
    nvidia_max_retries: int = 2
    nvidia_max_output_tokens: int = 1024

    @property
    def tenant_graphs(self):
        if self.loom_graph_namespace=='demo':return dict(TENANTS)
        return {tenant:f'loom_{self.loom_graph_namespace}_{tenant}' for tenant in TENANTS}


settings = Settings()
