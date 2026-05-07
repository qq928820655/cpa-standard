import { test, expect } from '@playwright/test'

const MASTER_KEY = 'cpa-ufN5DGQb7UlfB0ZKCPtHwrKMKSnmEz90vTKAy_JFjLU'
const VIEW_STATE_KEYS = [
  'keyManageViewState',
  'keyManageFiltersCollapsed',
  'dashboardViewState',
  'usageStatsViewState',
]

async function fetchKey(page, id) {
  return await page.evaluate(async ({ id }) => {
    const response = await fetch(`/api/admin/keys/${id}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('masterKey') || ''}`,
      },
    })
    const data = await response.json()
    return { ok: response.ok, status: response.status, data }
  }, { id })
}

async function fetchKeys(page, limit = 5) {
  return await page.evaluate(async ({ limit }) => {
    const response = await fetch(`/api/admin/keys?page=1&limit=${limit}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('masterKey') || ''}`,
      },
    })
    const data = await response.json()
    return { ok: response.ok, status: response.status, data }
  }, { limit })
}

async function setMasterKey(page) {
  await page.addInitScript(({ masterKey, stateKeys }) => {
    localStorage.setItem('masterKey', masterKey)
    stateKeys.forEach((key) => localStorage.removeItem(key))
  }, { masterKey: MASTER_KEY, stateKeys: VIEW_STATE_KEYS })

  await page.goto('/keys')
  await expect(page.getByRole('heading', { name: 'API Key 管理' })).toBeVisible()
}

async function getTestKeyIds(page, count = 2) {
  const result = await fetchKeys(page, Math.max(count, 5))
  expect(result.ok, 'should fetch visible keys from API').toBeTruthy()

  const items = Array.isArray(result.data)
    ? result.data
    : (Array.isArray(result.data?.items) ? result.data.items : [])

  const ids = items
    .map((item) => Number(item?.id))
    .filter((id) => Number.isInteger(id) && id > 0)
    .slice(0, count)

  expect(ids.length, 'should have enough keys for verification').toBeGreaterThanOrEqual(count)
  return ids
}

async function findRowByKeyId(page, keyId) {
  const rows = page.locator('.el-table__body-wrapper tbody tr')
  await expect(rows.first()).toBeVisible({ timeout: 30000 })

  const rowCount = await rows.count()
  for (let index = 0; index < rowCount; index += 1) {
    const row = rows.nth(index)
    const idText = (await row.locator('td').nth(1).innerText()).trim()
    if (Number(idText) === keyId) {
      return row
    }
  }

  throw new Error(`row for key ${keyId} not found in current table page`)
}

async function ensureKeyRowsVisible(page) {
  await expect(page.locator('.el-table__body-wrapper tbody tr').first()).toBeVisible({ timeout: 30000 })
}

async function showKeysByIds(page, keyIds) {
  const idsText = keyIds.join(',')
  await page.getByPlaceholder('输入 Key ID，支持中英文逗号分隔').fill(idsText)
  await page.getByRole('button', { name: '查询' }).click()
  await ensureKeyRowsVisible(page)
}


async function toggleRowSelection(page, keyId, selected) {
  const row = await findRowByKeyId(page, keyId)
  const checkbox = row.locator('.el-checkbox').first()
  const checkboxClass = await checkbox.getAttribute('class')
  const isSelected = String(checkboxClass || '').includes('is-checked')
  if (isSelected !== selected) {
    await checkbox.click()
  }
}

test('verify key proxy and fake ip persistence', async ({ page }) => {
  await setMasterKey(page)

  const dialog = page.getByRole('dialog', { name: /添加 API Key|编辑 API Key/ })
  const keyIds = await getTestKeyIds(page, 2)

  for (const keyId of keyIds) {
    const before = await fetchKey(page, keyId)
    expect(before.ok, `key ${keyId} should be queryable`).toBeTruthy()

    const key = before.data
    const nextEnableProxy = !Boolean(key.enable_proxy)
    const nextProxyUrl = nextEnableProxy ? 'http://127.0.0.1:65535' : ''
    const nextProxyUsername = nextEnableProxy ? 'cli-user' : ''
    const nextProxyPassword = nextEnableProxy ? 'cli-pass' : ''
    const nextEnableFakeIp = !Boolean(key.enable_fake_ip)
    const nextFakeIp = nextEnableFakeIp ? '203.0.113.10' : ''

    await page.getByRole('button', { name: '新增key' }).click()
    await expect(dialog).toBeVisible()

    await dialog.getByPlaceholder('输入名称标识').fill(key.name || '')
    await dialog.getByPlaceholder('输入 API Key').fill(key.api_key || '')
    await dialog.getByPlaceholder('输入 API 请求地址').fill(key.base_url || '')
    await dialog.getByRole('spinbutton').fill(String(Number(key.weight) || 1))

    const proxySwitch = dialog.locator('.proxy-config-wrap .el-switch').nth(0)
    const proxySwitchClass = await proxySwitch.getAttribute('class')
    const proxySwitchWasOn = String(proxySwitchClass || '').includes('is-checked')
    if (proxySwitchWasOn !== nextEnableProxy) {
      await proxySwitch.click()
    }

    const proxyUrlInput = dialog.getByPlaceholder('输入代理地址，例如 http://host:port')
    if (nextEnableProxy) {
      await expect(proxyUrlInput).toBeVisible()
      await proxyUrlInput.fill(nextProxyUrl)
      await dialog.getByPlaceholder('可选，输入代理账号').fill(nextProxyUsername)
      await dialog.getByPlaceholder('可选，输入代理密码').fill(nextProxyPassword)
    } else {
      await expect(proxyUrlInput).toHaveCount(0)
    }

    const fakeIpSwitch = dialog.locator('.proxy-config-wrap .el-switch').nth(1)
    const fakeIpSwitchClass = await fakeIpSwitch.getAttribute('class')
    const fakeIpSwitchWasOn = String(fakeIpSwitchClass || '').includes('is-checked')
    if (fakeIpSwitchWasOn !== nextEnableFakeIp) {
      await fakeIpSwitch.click()
    }

    const fakeIpInput = dialog.getByPlaceholder('输入要附带的 IPv4 或 IPv6 地址')
    if (nextEnableFakeIp) {
      await expect(fakeIpInput).toBeVisible()
      await fakeIpInput.fill(nextFakeIp)
    } else {
      await expect(fakeIpInput).toHaveCount(0)
    }

    await dialog.getByRole('button', { name: '取消' }).click()
    await expect(dialog).toBeHidden()

    const updateResponse = await page.evaluate(async ({ keyId, key, nextEnableProxy, nextProxyUrl, nextProxyUsername, nextProxyPassword, nextEnableFakeIp, nextFakeIp }) => {
      const payload = {
        name: key.name,
        provider: key.provider,
        api_key: key.api_key,
        base_url: key.base_url,
        weight: Number(key.weight) || 1,
        enable_proxy: nextEnableProxy,
        proxy_url: nextEnableProxy ? nextProxyUrl : null,
        proxy_username: nextEnableProxy ? nextProxyUsername : null,
        proxy_password: nextEnableProxy ? nextProxyPassword : null,
        enable_fake_ip: nextEnableFakeIp,
        fake_ip: nextEnableFakeIp ? nextFakeIp : null,
        supported_models: Array.isArray(key.supported_models) && key.supported_models.length ? key.supported_models : null,
        remark: key.remark || '',
      }
      const response = await fetch(`/api/admin/keys/${keyId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('masterKey') || ''}`,
        },
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      return { ok: response.ok, status: response.status, data }
    }, { keyId, key, nextEnableProxy, nextProxyUrl, nextProxyUsername, nextProxyPassword, nextEnableFakeIp, nextFakeIp })

    expect(updateResponse.ok, `key ${keyId} update should succeed`).toBeTruthy()

    const after = await fetchKey(page, keyId)
    expect(after.ok, `key ${keyId} should remain queryable after update`).toBeTruthy()
    expect(Boolean(after.data.enable_proxy)).toBe(nextEnableProxy)
    expect(after.data.proxy_url || '').toBe(nextEnableProxy ? nextProxyUrl : '')
    expect(after.data.proxy_username || '').toBe(nextEnableProxy ? nextProxyUsername : '')
    expect(after.data.proxy_password || '').toBe(nextEnableProxy ? nextProxyPassword : '')
    expect(Boolean(after.data.enable_fake_ip)).toBe(nextEnableFakeIp)
    expect(after.data.fake_ip || '').toBe(nextEnableFakeIp ? nextFakeIp : '')
  }
})

test('verify batch fake ip toggle in keys dialog', async ({ page }) => {
  await setMasterKey(page)

  const batchKeyIds = await getTestKeyIds(page, 2)
  await showKeysByIds(page, batchKeyIds)

  for (const keyId of batchKeyIds) {
    await toggleRowSelection(page, keyId, true)
  }

  await page.getByRole('button', { name: 'keys调整' }).click()
  const batchDialog = page.getByRole('dialog', { name: '批量调整地址和模型' })
  await expect(batchDialog).toBeVisible()

  const selectedScopeRadio = batchDialog.locator('label.el-radio').filter({ hasText: '当前勾选项' }).first()
  const enableFakeIpRadio = batchDialog.locator('label.el-radio').filter({ hasText: '开启并分配' }).first()
  const disableFakeIpRadio = batchDialog.locator('label.el-radio').filter({ hasText: '关闭并清空' }).first()

  await selectedScopeRadio.click()
  await enableFakeIpRadio.click()
  const enableResponsePromise = page.waitForResponse((response) => response.url().includes('/api/admin/keys/batch/fake-ip') && response.request().method() === 'POST' && response.status() === 200)
  await batchDialog.getByRole('button', { name: '确认调整' }).click()
  const enableResponse = await enableResponsePromise
  expect(enableResponse.ok()).toBeTruthy()
  await expect(batchDialog).toBeHidden({ timeout: 20000 })

  const enabledStates = []
  for (const keyId of batchKeyIds) {
    const current = await fetchKey(page, keyId)
    expect(current.ok, `key ${keyId} should be queryable after batch enable`).toBeTruthy()
    enabledStates.push(current.data)
  }

  enabledStates.forEach((item) => {
    expect(Boolean(item.enable_fake_ip)).toBeTruthy()
    expect(String(item.fake_ip || '')).toMatch(/^(?:10\.(?:\d{1,3})\.(?:\d{1,3})\.(?:\d{1,3})|172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3})\.(?:\d{1,3})|192\.168\.(?:\d{1,3})\.(?:\d{1,3})|198\.(?:51\.100|0\.2|113\.0)\.(?:\d{1,3}))$/)
  })
  const prefixes = enabledStates.map((item) => String(item.fake_ip || '').split('.').slice(0, 2).join('.'))
  expect(new Set(prefixes).size).toBe(prefixes.length)
  expect(enabledStates[0].fake_ip).not.toBe(enabledStates[1].fake_ip)

  await showKeysByIds(page, batchKeyIds)
  for (const keyId of batchKeyIds) {
    await toggleRowSelection(page, keyId, true)
  }

  await page.getByRole('button', { name: 'keys调整' }).click()
  await expect(batchDialog).toBeVisible()
  await selectedScopeRadio.click()
  await disableFakeIpRadio.click()
  const disableResponsePromise = page.waitForResponse((response) => response.url().includes('/api/admin/keys/batch/fake-ip') && response.request().method() === 'POST' && response.status() === 200)
  await batchDialog.getByRole('button', { name: '确认调整' }).click()
  const disableResponse = await disableResponsePromise
  expect(disableResponse.ok()).toBeTruthy()
  await expect(batchDialog).toBeHidden({ timeout: 20000 })

  for (const keyId of batchKeyIds) {
    const current = await fetchKey(page, keyId)
    expect(current.ok, `key ${keyId} should be queryable after batch disable`).toBeTruthy()
    expect(Boolean(current.data.enable_fake_ip)).toBeFalsy()
    expect(current.data.fake_ip).toBeFalsy()
  }
})
