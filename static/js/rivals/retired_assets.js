/** Host of the deleted Supabase project. Those URLs 404. Skip them before fetch. */
export const RETIRED_ASSET_HOST = "biofeygmxomcpaxqkgfe.supabase.co";

export function isRetiredAssetUrl(url) {
  return typeof url === "string" && url.includes(RETIRED_ASSET_HOST);
}
