"""Service for managing and validating API keys."""
import logging
from dataclasses import dataclass
from datetime import datetime

from anthropic import AsyncAnthropic
from anthropic import AuthenticationError as AnthropicAuthError
from anthropic import RateLimitError as AnthropicRateLimitError
from openai import AsyncOpenAI
from openai import AuthenticationError as OpenAIAuthError
from openai import RateLimitError as OpenAIRateLimitError
from sqlalchemy.orm import Session

from app.models.api_key import APIKey, APIKeyStatus, APIProvider
from app.services.encryption import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)


@dataclass
class APIKeyValidationResult:
    """Result of API key validation."""

    valid: bool
    status: APIKeyStatus
    error: str | None = None


class APIKeyService:
    """Service for API key management."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id

    def get_key(self, provider: APIProvider) -> APIKey | None:
        """Get API key for a provider."""
        return self.db.query(APIKey).filter(
            APIKey.provider == provider.value, APIKey.user_id == self.user_id
        ).first()

    def get_all_keys(self) -> list[APIKey]:
        """Get all stored API keys."""
        return self.db.query(APIKey).filter(APIKey.user_id == self.user_id).all()

    def get_decrypted_key(self, provider: APIProvider) -> str | None:
        """Get decrypted API key value for a provider."""
        key = self.get_key(provider)
        if key:
            return decrypt_api_key(key.encrypted_key)
        return None

    def resolve_key(self, provider: APIProvider) -> str | None:
        """Resolve API key from the user's stored DB key.

        This is the single source of truth for which key to use.
        """
        return self.get_decrypted_key(provider)

    def save_key(
        self,
        provider: APIProvider,
        key_value: str,
        status: APIKeyStatus = APIKeyStatus.UNKNOWN,
        error: str | None = None,
    ) -> APIKey:
        """Save or update an API key."""
        existing = self.get_key(provider)
        encrypted = encrypt_api_key(key_value)
        key_suffix = key_value[-4:] if len(key_value) >= 4 else key_value

        if existing:
            existing.encrypted_key = encrypted
            existing.key_suffix = key_suffix
            existing.status = status.value
            existing.last_error = error
            existing.last_validated_at = datetime.utcnow() if status != APIKeyStatus.UNKNOWN else None
            existing.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            new_key = APIKey(
                user_id=self.user_id,
                provider=provider.value,
                encrypted_key=encrypted,
                key_suffix=key_suffix,
                status=status.value,
                last_error=error,
                last_validated_at=datetime.utcnow() if status != APIKeyStatus.UNKNOWN else None,
            )
            self.db.add(new_key)
            self.db.commit()
            self.db.refresh(new_key)
            return new_key

    def delete_key(self, provider: APIProvider) -> bool:
        """Delete an API key."""
        key = self.get_key(provider)
        if key:
            self.db.delete(key)
            self.db.commit()
            return True
        return False

    async def validate_openai_key(self, key_value: str) -> APIKeyValidationResult:
        """Validate an OpenAI API key by making a minimal API call."""
        try:
            client = AsyncOpenAI(api_key=key_value)
            # Use models.list() as a lightweight validation call
            await client.models.list()
            return APIKeyValidationResult(valid=True, status=APIKeyStatus.ACTIVE)
        except OpenAIAuthError:
            return APIKeyValidationResult(
                valid=False, status=APIKeyStatus.INVALID, error="Invalid API key"
            )
        except OpenAIRateLimitError as e:
            error_msg = str(e).lower()
            # Check if it's a quota issue vs rate limit
            if "quota" in error_msg or "exceeded" in error_msg:
                return APIKeyValidationResult(
                    valid=True, status=APIKeyStatus.QUOTA_EXCEEDED, error=str(e)
                )
            # Rate limit means key is valid but temporarily limited
            return APIKeyValidationResult(valid=True, status=APIKeyStatus.ACTIVE, error=str(e))
        except Exception as e:
            logger.error(f"OpenAI validation error: {e}")
            return APIKeyValidationResult(
                valid=False, status=APIKeyStatus.UNKNOWN, error=str(e)
            )

    async def validate_anthropic_key(self, key_value: str) -> APIKeyValidationResult:
        """Validate an Anthropic API key by making a minimal API call."""
        try:
            client = AsyncAnthropic(api_key=key_value)
            # Make a minimal message request to validate
            await client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return APIKeyValidationResult(valid=True, status=APIKeyStatus.ACTIVE)
        except AnthropicAuthError:
            return APIKeyValidationResult(
                valid=False, status=APIKeyStatus.INVALID, error="Invalid API key"
            )
        except AnthropicRateLimitError as e:
            error_msg = str(e).lower()
            if "quota" in error_msg or "exceeded" in error_msg:
                return APIKeyValidationResult(
                    valid=True, status=APIKeyStatus.QUOTA_EXCEEDED, error=str(e)
                )
            return APIKeyValidationResult(valid=True, status=APIKeyStatus.ACTIVE, error=str(e))
        except Exception as e:
            logger.error(f"Anthropic validation error: {e}")
            return APIKeyValidationResult(
                valid=False, status=APIKeyStatus.UNKNOWN, error=str(e)
            )

    async def validate_fal_key(self, key_value: str) -> APIKeyValidationResult:
        """Validate a fal.ai API key by making a lightweight API call."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://queue.fal.run/fal-ai/flux/dev/requests",
                    headers={"Authorization": f"Key {key_value}"},
                )
                if resp.status_code == 401:
                    return APIKeyValidationResult(
                        valid=False, status=APIKeyStatus.INVALID, error="Invalid API key"
                    )
                # Any non-401 response means the key is accepted
                return APIKeyValidationResult(valid=True, status=APIKeyStatus.ACTIVE)
        except Exception as e:
            logger.error(f"fal.ai validation error: {e}")
            return APIKeyValidationResult(
                valid=False, status=APIKeyStatus.UNKNOWN, error=str(e)
            )

    async def validate_and_save_key(
        self,
        provider: APIProvider,
        key_value: str,
    ) -> tuple[APIKey, APIKeyValidationResult]:
        """Validate a key and save it with the validation result."""
        if provider == APIProvider.OPENAI:
            result = await self.validate_openai_key(key_value)
        elif provider == APIProvider.ANTHROPIC:
            result = await self.validate_anthropic_key(key_value)
        elif provider == APIProvider.FAL:
            result = await self.validate_fal_key(key_value)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        api_key = self.save_key(
            provider=provider,
            key_value=key_value,
            status=result.status,
            error=result.error,
        )

        return api_key, result


def get_api_key_service(db: Session, user_id: int) -> APIKeyService:
    """Factory function to get APIKeyService instance."""
    return APIKeyService(db, user_id)
