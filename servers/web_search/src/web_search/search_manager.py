"""Search manager for coordinating different search providers."""

import os
from typing import Dict, Type, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv is optional
    def load_dotenv():
        pass
    load_dotenv()

try:
    from .search_types import SearchProvider, SearchConfig, SearchResponse
    from .providers.base import BaseSearchProvider
    from .providers.serpapi_provider import SerpAPIProvider
    from .providers.perplexity_provider import PerplexityProvider
    from .providers.duckduckgo_provider import DuckDuckGoProvider
    from .providers.tavily_provider import TavilyProvider
    from .providers.claude_provider import ClaudeProvider
except ImportError:
    # For running as script
    from search_types import SearchProvider, SearchConfig, SearchResponse
    from providers.base import BaseSearchProvider
    from providers.serpapi_provider import SerpAPIProvider
    from providers.perplexity_provider import PerplexityProvider
    from providers.duckduckgo_provider import DuckDuckGoProvider
    from providers.tavily_provider import TavilyProvider
    from providers.claude_provider import ClaudeProvider

# Environment variables are loaded above


class SearchManager:
    """Manages different search providers and routing."""
    
    # Provider class mapping
    PROVIDERS: Dict[SearchProvider, Type[BaseSearchProvider]] = {
        SearchProvider.SERPAPI: SerpAPIProvider,
        SearchProvider.PERPLEXITY: PerplexityProvider,
        SearchProvider.DUCKDUCKGO: DuckDuckGoProvider,
        SearchProvider.TAVILY: TavilyProvider,
        SearchProvider.CLAUDE: ClaudeProvider,
    }
    
    def __init__(self, default_provider: SearchProvider = SearchProvider.DUCKDUCKGO):
        self.default_provider = default_provider
        self._configs: Dict[SearchProvider, SearchConfig] = {}
        self._load_configs()
    
    def _load_configs(self):
        """Load configurations for all providers from environment variables."""
        
        # SerpAPI configuration
        self._configs[SearchProvider.SERPAPI] = SearchConfig(
            provider=SearchProvider.SERPAPI,
            api_key=os.getenv("SERPAPI_API_KEY"),
            max_results=int(os.getenv("SERPAPI_MAX_RESULTS", "10")),
            serpapi_engine=os.getenv("SERPAPI_ENGINE", "google"),
            timeout=int(os.getenv("SEARCH_TIMEOUT", "30"))
        )
        
        # Perplexity configuration
        self._configs[SearchProvider.PERPLEXITY] = SearchConfig(
            provider=SearchProvider.PERPLEXITY,
            api_key=os.getenv("PERPLEXITY_API_KEY"),
            max_results=int(os.getenv("PERPLEXITY_MAX_RESULTS", "10")),
            perplexity_model=os.getenv("PERPLEXITY_MODEL", "sonar-pro"),
            timeout=int(os.getenv("SEARCH_TIMEOUT", "30"))
        )
        
        # DuckDuckGo configuration (no API key required)
        self._configs[SearchProvider.DUCKDUCKGO] = SearchConfig(
            provider=SearchProvider.DUCKDUCKGO,
            max_results=int(os.getenv("DUCKDUCKGO_MAX_RESULTS", "10")),
            duckduckgo_safesearch=os.getenv("DUCKDUCKGO_SAFESEARCH", "moderate"),
            timeout=int(os.getenv("SEARCH_TIMEOUT", "30"))
        )
        
        # Tavily configuration
        self._configs[SearchProvider.TAVILY] = SearchConfig(
            provider=SearchProvider.TAVILY,
            api_key=os.getenv("TAVILY_API_KEY"),
            max_results=int(os.getenv("TAVILY_MAX_RESULTS", "10")),
            timeout=int(os.getenv("SEARCH_TIMEOUT", "30"))
        )
        
        # Claude configuration
        self._configs[SearchProvider.CLAUDE] = SearchConfig(
            provider=SearchProvider.CLAUDE,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_results=int(os.getenv("CLAUDE_MAX_RESULTS", "10")),
            timeout=int(os.getenv("SEARCH_TIMEOUT", "30"))
        )
    
    def get_available_providers(self) -> Dict[str, bool]:
        """Get list of available providers and their status."""
        status = {}
        
        for provider in SearchProvider:
            config = self._configs[provider]
            
            # Check if provider is available
            if provider == SearchProvider.DUCKDUCKGO:
                # DuckDuckGo doesn't require API key
                status[provider.value] = True
            else:
                # Other providers require API keys
                status[provider.value] = bool(config.api_key)
        
        return status
    
    async def search(
        self, 
        query: str, 
        provider: Optional[SearchProvider] = None,
        max_results: Optional[int] = None
    ) -> SearchResponse:
        """Perform search using specified or default provider."""
        
        # Use specified provider or fall back to default
        search_provider = provider or self.default_provider
        
        # Get provider configuration
        config = self._configs[search_provider].model_copy()
        
        # Override max_results if specified
        if max_results:
            config.max_results = max_results
        
        # Get provider class and perform search
        provider_class = self.PROVIDERS[search_provider]
        
        async with provider_class(config) as search_client:
            return await search_client.search(query)
    
    async def multi_provider_search(
        self, 
        query: str, 
        providers: list[SearchProvider],
        max_results_per_provider: int = 5
    ) -> Dict[str, SearchResponse]:
        """Perform search across multiple providers simultaneously."""
        results = {}
        
        # TODO: Implement concurrent searches
        for provider in providers:
            try:
                response = await self.search(
                    query=query, 
                    provider=provider, 
                    max_results=max_results_per_provider
                )
                results[provider.value] = response
            except Exception as e:
                # Log error but continue with other providers
                results[provider.value] = SearchResponse(
                    query=query,
                    provider=provider,
                    results=[],
                    metadata={"error": str(e)}
                )
        
        return results
    
    def get_fallback_chain(self) -> list[SearchProvider]:
        """Get fallback chain of providers to try in order."""
        available = self.get_available_providers()
        
        # Priority order: DuckDuckGo (free) -> SerpAPI -> Perplexity -> Tavily -> Claude
        fallback_order = [
            SearchProvider.DUCKDUCKGO,
            SearchProvider.SERPAPI,
            SearchProvider.PERPLEXITY,
            SearchProvider.TAVILY,
            SearchProvider.CLAUDE
        ]
        
        return [p for p in fallback_order if available.get(p.value, False)]
    
    async def search_with_fallback(self, query: str, max_results: int = 10) -> SearchResponse:
        """Search with automatic fallback to other providers if primary fails."""
        fallback_chain = self.get_fallback_chain()
        
        last_error = None
        
        for provider in fallback_chain:
            try:
                return await self.search(query, provider, max_results)
            except Exception as e:
                last_error = e
                continue
        
        # If all providers failed, return error response
        return SearchResponse(
            query=query,
            provider=SearchProvider.DUCKDUCKGO,  # Default
            results=[],
            metadata={
                "error": f"All providers failed. Last error: {str(last_error)}",
                "attempted_providers": [p.value for p in fallback_chain]
            }
        )