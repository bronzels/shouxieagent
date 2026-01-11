"""
LLM Client Module

This module provides a unified interface for OpenAI-compatible LLM APIs.
Configuration is loaded from .env file. To switch providers, just update .env.

Provides two interfaces:
1. get_chat_openai() - Returns LangChain ChatOpenAI for use with agents
2. get_llm_client() / LLMClient - Direct REST API client for custom usage
"""

import os
from pathlib import Path
import requests
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any

from langchain_openai import ChatOpenAI

# Load environment variables from .env file in project root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def get_chat_openai() -> ChatOpenAI:
    """
    Get a LangChain-compatible ChatOpenAI instance.
    
    This is compatible with LangChain agents like create_tool_calling_agent.
    Configuration is loaded from environment variables:
    - LLM_API_URL: The API endpoint base URL
    - LLM_API_KEY: The API key/token
    - LLM_MODEL: The model to use
    
    Returns:
        ChatOpenAI instance configured for the provider in .env
    """
    api_url = os.getenv("LLM_API_URL")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    
    if not api_url:
        raise ValueError("LLM_API_URL not configured. Set it in .env")
    if not api_key:
        raise ValueError("LLM_API_KEY not configured. Set it in .env")
    if not model:
        raise ValueError("LLM_MODEL not configured. Set it in .env")
    
    # Extract base URL (remove /chat/completions if present)
    base_url = api_url.replace("/chat/completions", "")
    
    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=0.7,
        max_tokens=4096
    )


class LLMClient:
    """
    A direct REST API client for interacting with OpenAI-compatible LLM APIs.
    
    Use this for custom API calls not covered by LangChain.
    For LangChain agents, use get_llm_client() instead.
    
    Configuration is loaded from environment variables:
    - LLM_API_URL: The API endpoint URL
    - LLM_API_KEY: The API key/token
    - LLM_MODEL: The model to use
    """
    
    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize the LLM client.
        
        Args:
            api_url: Override the API URL from .env
            api_key: Override the API key from .env
            model: Override the model from .env
        """
        self.api_url = api_url or os.getenv("LLM_API_URL")
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.model = model or os.getenv("LLM_MODEL")
        
        if not self.api_url:
            raise ValueError("LLM_API_URL not configured. Set it in .env or pass as argument.")
        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured. Set it in .env or pass as argument.")
        if not self.model:
            raise ValueError("LLM_MODEL not configured. Set it in .env or pass as argument.")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get the request headers with authorization."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.7,
        top_k: int = 50,
        frequency_penalty: float = 0.5,
        stop: Optional[List[str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to the LLM API.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
            stream: Whether to stream the response
            max_tokens: Maximum tokens in the response
            temperature: Sampling temperature (0-1)
            top_p: Top-p sampling parameter
            top_k: Top-k sampling parameter
            frequency_penalty: Frequency penalty for token repetition
            stop: List of stop sequences
            tools: List of tool definitions for function calling
            response_format: Response format specification
            **kwargs: Additional provider-specific parameters
        
        Returns:
            The API response as a dictionary
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "frequency_penalty": frequency_penalty,
            "n": 1,
        }
        
        if stop is not None:
            payload["stop"] = stop
        
        if tools is not None:
            payload["tools"] = tools
        
        if response_format is not None:
            payload["response_format"] = response_format
        else:
            payload["response_format"] = {"type": "text"}
        
        # Add any additional provider-specific parameters
        payload.update(kwargs)
        
        response = requests.post(
            self.api_url,
            json=payload,
            headers=self._get_headers()
        )
        
        response.raise_for_status()
        return response.json()
    
    def simple_chat(self, prompt: str, **kwargs) -> str:
        """
        Simple helper for single-turn chat.
        
        Args:
            prompt: The user's prompt
            **kwargs: Additional parameters to pass to chat()
        
        Returns:
            The assistant's response text
        """
        messages = [{"role": "user", "content": prompt}]
        response = self.chat(messages, **kwargs)
        return response["choices"][0]["message"]["content"]


def get_llm_client() -> LLMClient:
    """Get a configured LLMClient instance for direct REST API calls."""
    return LLMClient()


if __name__ == "__main__":
    print("=" * 50)
    print("Testing get_chat_openai() - LangChain ChatOpenAI")
    print("=" * 50)
    llm = get_chat_openai()
    response = llm.invoke("Say 'Hello from ChatOpenAI' in one sentence.")
    print(response.content)
    
    print()
    print("=" * 50)
    print("Testing get_llm_client() - Direct REST API Client")
    print("=" * 50)
    client = get_llm_client()
    response = client.simple_chat("Say 'Hello from LLMClient' in one sentence.")
    print(response)
