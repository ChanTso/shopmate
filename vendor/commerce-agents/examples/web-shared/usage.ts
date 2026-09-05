/** Format measured provider usage without turning an absent measurement into zero. */
interface ProviderUsage {
  usage_complete: boolean;
  model_calls: number;
  calls_with_usage: number;
  known_input_tokens: number;
  known_output_tokens: number;
  known_cache_read_input_tokens: number;
}

export function formatTurnUsage(data: Record<string, unknown>): string {
  const n = (value?: number) => value == null ? "unknown" : value.toLocaleString("en-US");
  const provider = data.provider_usage as ProviderUsage | undefined;
  if (provider) {
    if (!provider.usage_complete && provider.calls_with_usage === 0) {
      return `usage unknown · ${n(provider.model_calls)} model calls`;
    }
    const measured = `in ${n(provider.known_input_tokens)} · out ${n(provider.known_output_tokens)}` +
      ` · cache read ${n(provider.known_cache_read_input_tokens)}`;
    return provider.usage_complete ? measured :
      `known ${measured} · total unknown (${n(provider.calls_with_usage)}/${n(provider.model_calls)} calls reported)`;
  }
  const usage = (data.usage ?? {}) as Record<string, number>;
  return `in ${n(usage.input_tokens)} · out ${n(usage.output_tokens)}` +
    ` · cache read ${n(usage.cache_read_input_tokens)}`;
}
