import json
import os
import time
from abc import ABC, abstractmethod

import requests
from google import genai
from groq import Groq
from openai import OpenAI


# Requires env variables
# GENAI_API_KEY=...
# OPENAI_API_KEY=...
# UFAL_API_KEY=...
# GROQ_API_KEY=...


class LLMClient(ABC):
    """Abstract base class for LLM chat clients."""

    def chat(
        self,
        messages: list[dict],
        retries: int = 1,
        delay: int = 30,
    ) -> str:
        """
        Send chat messages to an LLM provider with transient-error retries.

        Parameters
        ----------
        messages : list[dict]
            Chat messages to send to the provider.
        retries : int, default=1
            Number of retries after the first failed attempt.
        delay : int, default=30
            Delay in seconds between retries.

        Returns
        -------
        str
            Model response text.
        """
        for attempt in range(retries + 1):
            try:
                return self._chat_once(messages)
            except Exception as error:
                if not should_retry_llm_error(error) or attempt == retries:
                    raise
                print(f"Transient LLM error: {error}. Another attempt...")
                time.sleep(delay)

        raise RuntimeError("LLM chat retry loop exited without returning.")

    @abstractmethod
    def _chat_once(self, messages: list[dict]) -> str:
        """
        Send chat messages to an LLM provider without retries.

        Parameters
        ----------
        messages : list[dict]
            Chat messages to send to the provider.

        Returns
        -------
        str
            Model response text.
        """


def should_retry_llm_error(error: Exception) -> bool:
    """
    Determine whether an LLM error is likely transient.

    Parameters
    ----------
    error : Exception
        Raised exception to classify.

    Returns
    -------
    bool
        True when the exception should be retried.
    """
    if isinstance(
        error,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ),
    ):
        return True

    status_code = get_http_status_code(error)
    return status_code == 429 or (status_code is not None and 500 <= status_code < 600)


def get_http_status_code(error: Exception) -> int | None:
    """
    Extract an HTTP status code from a provider exception.

    Parameters
    ----------
    error : Exception
        Provider exception.

    Returns
    -------
    int | None
        HTTP status code when available.
    """
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        return int(status_code)

    code = getattr(error, "code", None)
    if isinstance(code, int):
        return code

    response = getattr(error, "response", None)
    if response is None:
        return None

    for attribute_name in ("status_code", "status"):
        attribute_value = getattr(response, attribute_name, None)
        if isinstance(attribute_value, int):
            return attribute_value

    return None


class OpenAIClient(LLMClient):
    """OpenAI API client using the Responses API."""

    def __init__(
        self,
        model: str = "gpt-5.6-terra",
        api_key: str | None = None,
        temperature: float | None = None,
        reasoning: str | None = None,
    ) -> None:
        self.client = OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model
        self.temperature = temperature
        self.reasoning = reasoning

    def _to_responses_input(self, messages: list[dict]) -> list[dict]:
        items = []
        for m in messages:
            role = m["role"]
            content = m["content"]

            # Responses API expects structured content items
            content_type = "output_text" if role == "assistant" else "input_text"
            items.append({
                "role": role,
                "content": [
                    {
                        "type": content_type,
                        "text": content,
                    }
                ],
            })
        return items

    def _chat_once(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "input": self._to_responses_input(messages),
        }

        if self.temperature is not None:
            payload["temperature"] = self.temperature

        if self.reasoning is not None:
            payload["reasoning"] = {"effort": self.reasoning}

        resp = self.client.responses.create(**payload)
        return resp.output_text


class GroqClient(LLMClient):
    """Groq API client."""

    def __init__(
        self,
        model: str = "openai/gpt-oss-120b",
        api_key: str | None = None,
        temperature: float | None = None,
        reasoning: str | None = None,
    ) -> None:
        self.client = Groq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model = model
        self.temperature = temperature
        self.reasoning = reasoning

    def _chat_once(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
        }

        if self.temperature is not None:
            payload["temperature"] = self.temperature

        if self.reasoning is not None:
            payload["reasoning_effort"] = self.reasoning

        resp = self.client.chat.completions.create(**payload)
        return resp.choices[0].message.content


class GenAIClient(LLMClient):
    """Google GenAI (Gemini) client."""

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        temperature: float | None = None,
        reasoning: str | None = None,
    ) -> None:

        self.client = genai.Client(api_key=api_key or os.environ["GENAI_API_KEY"])
        self.model = model
        self.temperature = temperature
        self.reasoning = reasoning

    def _chat_once(self, messages: list[dict]) -> str:
        system = ""
        user_parts = []

        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            elif m["role"] == "user":
                user_parts.append(m["content"])
            else:
                user_parts.append(f"{m['role'].upper()}: {m['content']}")

        config_kwargs = {}
        if system.strip():
            config_kwargs["system_instruction"] = system.strip()
        if self.temperature is not None:
            config_kwargs["temperature"] = self.temperature

        # This may vary by SDK/model support
        if self.reasoning is not None:
            budget_map = {
                "none": 0,
                "low": 1024,
                "medium": 4096,
                "high": 8192,
            }
            config_kwargs["thinking_config"] = genai.types.ThinkingConfig(
                thinking_budget=budget_map.get(self.reasoning, 4096)
            )

        chat = self.client.chats.create(
            model=self.model,
            config=genai.types.GenerateContentConfig(**config_kwargs),
        )
        resp = chat.send_message("\n\n".join(user_parts))
        return resp.text


class UfalClient(LLMClient):
    """UFAL AI API client."""

    def __init__(
        self,
        model: str = "Apertus-70B-8b_4x3090.RedHatAI/Apertus-70B-Instruct-2509-FP8-dynamic",
        api_token: str | None = None,
        temperature: float | None = 0.0,
        reasoning: str | None = None,
    ) -> None:
        self.model = model
        self.api_url = "https://ai.ufal.mff.cuni.cz/api/chat/completions"
        self.timeout = 120
        self.api_token = api_token or os.environ["UFAL_API_KEY"]
        self.temperature = temperature
        self.reasoning = reasoning

    def _chat_once(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
        }

        if self.temperature is not None:
            payload["temperature"] = self.temperature

        if self.reasoning is not None:
            payload["reasoning"] = {"effort": self.reasoning}

        r = requests.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"Unexpected UFAL response shape: {data}")


def get_llm(
    provider: str,
    model: str | None = None,
    temperature: float | None = None,
    reasoning: str | None = None,
    api_key: str | None = None,
) -> LLMClient:
    kwargs = {
        "temperature": temperature,
        "reasoning": reasoning,
    }
    if model is not None:
        kwargs["model"] = model

    if provider == "openai":
        kwargs["api_key"] = api_key
        return OpenAIClient(**kwargs)

    elif provider == "genai":
        kwargs["api_key"] = api_key
        return GenAIClient(**kwargs)

    elif provider == "ufalai":
        kwargs["api_token"] = api_key
        return UfalClient(**kwargs)

    elif provider == "groq":
        kwargs["api_key"] = api_key
        return GroqClient(**kwargs)

    else:
        raise ValueError(f"Unknown provider: {provider}")
