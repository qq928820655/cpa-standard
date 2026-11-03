const runtime = window.CpaPluginRuntime

if (!runtime?.adminApi) {
  throw new Error('CPA plugin runtime is unavailable')
}

export const adminApi = runtime.adminApi
