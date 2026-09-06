export interface WebSource {
  url: string;
  title?: string;
}

export interface WebCitation extends WebSource {
  title: string;
  start_index?: number;
  end_index?: number;
}

export interface WebSourcesPayload {
  query: string;
  summary: string;
  citations: WebCitation[];
  consulted_sources: WebSource[];
  sources_available: boolean;
  search_calls: number;
  summary_truncated?: boolean;
}

export interface SourceLink {
  href: string;
  title: string;
  hostname: string;
  number: number;
}

/** Links are provider metadata; the answer's text never creates a source. */
export function sourceLinks(sources: readonly WebSource[]): SourceLink[] {
  return sources.flatMap((source, index) => {
    if (typeof source.url !== "string" || !/^https?:\/\//i.test(source.url) || /[\u0000-\u0020\u007f]/.test(source.url)) return [];
    try {
      const url = new URL(source.url);
      if (!url.hostname || url.username || url.password) return [];
      return [{ href: url.href, title: source.title?.trim() || url.hostname, hostname: url.hostname, number: index + 1 }];
    } catch { return []; }
  });
}
