import type { ProviderConfigView, ProviderLastTestResult, ProviderModelCache } from './types';
import {
  mergeProviderModelTokenLimits,
  resolveProviderModelTokenState,
} from '../../../shared/src/providerModelTokenLimits';

export interface RestoredProviderStateInput {
  baseProviderConfig: ProviderConfigView;
  cache?: ProviderModelCache;
  cacheUsable: boolean;
  lastTestResult?: ProviderLastTestResult;
}

export function buildRestoredProviderConfigView({
  baseProviderConfig,
  cache,
  cacheUsable,
  lastTestResult,
}: RestoredProviderStateInput): ProviderConfigView {
  const hardBlockedByLastTest = Boolean(
    lastTestResult && lastTestResult.ok === false && isRestoreBlockingFailure(lastTestResult),
  );
  const hardBlockedByCache = isRestoreBlockingFailure({
    errorCategory: cache?.lastErrorCategory,
    detail: cache?.lastError,
  });
  const restoreBlockedByLastTest = hardBlockedByLastTest;
  const allowCachedModels = cacheUsable && !restoreBlockedByLastTest;
  const restoredModelTokenLimits =
    allowCachedModels || hardBlockedByCache
      ? mergeProviderModelTokenLimits(baseProviderConfig.modelTokenLimits, cache?.modelTokenLimits)
      : baseProviderConfig.modelTokenLimits;
  const restoredTokenState = resolveProviderModelTokenState(
    {
      model: baseProviderConfig.model,
      contextWindowTokens: baseProviderConfig.contextWindowTokens,
      maxOutputTokens: baseProviderConfig.maxOutputTokens,
      modelTokenLimits: restoredModelTokenLimits,
    },
    baseProviderConfig.model,
    {
      modelTokenLimits: restoredModelTokenLimits,
      hasModelTokenLimits: true,
      hasContextWindowTokens: false,
      hasMaxOutputTokens: false,
    },
  );

  return {
    ...baseProviderConfig,
    contextWindowTokens: restoredTokenState.contextWindowTokens,
    maxOutputTokens: restoredTokenState.maxOutputTokens,
    availableModels: allowCachedModels ? cache?.availableModels ?? [] : [],
    modelTokenLimits: restoredTokenState.modelTokenLimits,
    resolvedModel: allowCachedModels ? cache?.resolvedModel : undefined,
    modelListStatus:
      restoreBlockedByLastTest || hardBlockedByCache
        ? 'error'
        : allowCachedModels
          ? 'ready'
          : 'idle',
    modelListDetail: restoreBlockedByLastTest
      ? lastTestResult?.detail
      : hardBlockedByCache
        ? cache?.lastError || 'Trainer restored the last provider failure for this provider.'
        : allowCachedModels
          ? cache?.lastError || 'Trainer restored the cached model list for this provider.'
          : baseProviderConfig.modelListDetail,
    cacheFetchedAt: allowCachedModels ? cache?.fetchedAt : undefined,
    cacheExpiresAt: allowCachedModels ? cache?.expiresAt : undefined,
    cacheSource: allowCachedModels || hardBlockedByCache ? 'cache' : undefined,
    modelErrorCategory: restoreBlockedByLastTest
      ? lastTestResult?.errorCategory
      : hardBlockedByCache || allowCachedModels
        ? cache?.lastErrorCategory
        : undefined,
    modelStatusCode: restoreBlockedByLastTest
      ? lastTestResult?.statusCode
      : hardBlockedByCache || allowCachedModels
        ? cache?.lastStatusCode
        : undefined,
    modelRetryable: restoreBlockedByLastTest
      ? lastTestResult?.retryable
      : hardBlockedByCache || allowCachedModels
        ? cache?.retryable
        : undefined,
    lastTestResult,
  };
}

function isRestoreBlockingFailure(
  result:
    | {
        errorCategory?: string;
        status?: string;
        detail?: string;
      }
    | undefined,
): boolean {
  if (!result) {
    return false;
  }

  const normalizedCategory = result.errorCategory?.trim();
  const normalizedStatus = result.status?.trim();
  if (
    normalizedCategory &&
    restoreBlockingCategories.has(normalizedCategory)
  ) {
    return true;
  }
  if (normalizedStatus && restoreBlockingCategories.has(normalizedStatus)) {
    return true;
  }

  const detail = result.detail?.toLowerCase() ?? '';
  return (
    /empty_response|truncated_or_empty|language_corruption/.test(detail) ||
    /empty content|truncated before any usable final content|no final coaching reply content|reasoning-only content|final reply content|question marks|corrupted chinese input/.test(
      detail,
    )
  );
}

const restoreBlockingCategories = new Set([
  'invalid_key_or_permission',
  'model_unsupported',
  'model_not_found',
  'malformed_response',
  'language_corruption',
  'empty_response',
  'truncated_or_empty',
]);
